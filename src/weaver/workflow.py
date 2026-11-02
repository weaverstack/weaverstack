"""One workflow: its configuration, its Session and one workflow ID.

.. code-block:: python

    import weaver

    with weaver.workflow():
        weaver.load(stale=True)
        weaver.test(stale=True)
        weaver.health()

An operation given no Session inside a workflow runs on the workflow's Session
and inherits its configuration, as an operation given that Session explicitly
does. Its own arguments override that configuration for that call only.

The workflow applies to the thread, or asyncio task, that entered it.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Mapping

from .errors import CommandError

if TYPE_CHECKING:
    from .sessions.base import Session
    from .workspaces import ExecutionSettings, Workspace


@dataclass(frozen=True)
class Workflow:
    """The configuration and Session an entered workflow's operations share.

    ``workspace`` is None only for a borrowed Session that has none, whose
    operations then resolve configuration as they would without a workflow.
    """

    workspace: "Workspace | None"
    session: "Session"
    workflow_id: str


_ACTIVE: ContextVar[Workflow | None] = ContextVar("weaver_workflow", default=None)


def active_workflow() -> Workflow | None:
    return _ACTIVE.get()


@contextmanager
def workflow(
    *,
    session: "Session | None" = None,
    workspace: str | None = None,
    workspace_config: str | Path | None = None,
    catalogue: str | None = None,
    environment: str | None = None,
    mirror: str | None = None,
    execution: "ExecutionSettings | Mapping[str, Any] | None" = None,
    targets: Mapping[Any, Any] | None = None,
    data_sources: Mapping[str, str] | None = None,
    catalogue_dashboard: str | None = None,
    credential: Any = None,
) -> Iterator[Workflow]:
    """Run operations in one Session, under one workflow ID.

    Configuration resolves as an operation's does: ``workspace`` and
    ``workspace_config``, then the Session's or the enclosing workflow's own,
    then ``workspace-config.yml`` in the working directory, then the Fabric
    notebook's workspace. ``catalogue`` and ``environment`` override what
    resolves. ``mirror``, ``execution``, ``targets``, ``data_sources`` and
    ``catalogue_dashboard`` each replace the resolved value whole, in the
    shapes workspace configuration uses.

    Without ``session``, the workflow borrows an enclosing workflow's Session,
    or opens one and closes it on exit. A given Session is borrowed and left
    open. ``credential`` applies only to a Session the workflow opens.

    A workflow resolves no items and starts nothing. Load and Test record under
    its workflow ID wherever they run.
    """

    from .config import with_overrides
    from .run import new_workflow_id

    outer = active_workflow()
    borrowed = session if session is not None else getattr(outer, "session", None)
    if borrowed is not None and borrowed.closed:
        raise CommandError("The Session is closed.")
    if borrowed is not None and credential is not None:
        raise CommandError(
            "credential applies only to a Session the workflow opens. "
            "Give it to that Session instead."
        )

    named = {"workspace": workspace, "workspace_config": workspace_config}
    overrides = {
        "catalogue": catalogue,
        "environment": environment,
        "mirror": mirror,
        "execution": execution,
        "targets": targets,
        "data_sources": data_sources,
        "catalogue_dashboard": catalogue_dashboard,
    }
    configured = any(
        value is not None for value in (*named.values(), *overrides.values())
    )
    inherited = _inherited(borrowed)
    if borrowed is not None and not configured and inherited is None:
        resolved = None
    else:
        from .operations.workspace import _operation_workspace

        base = _operation_workspace(
            **named,
            catalogue=catalogue,
            environment=environment,
            session=borrowed,
        )
        resolved = with_overrides(
            base,
            {
                name: value
                for name, value in overrides.items()
                if name not in ("catalogue", "environment")
            },
        )

    if borrowed is not None:
        opened, owned = borrowed, False
    else:
        from .sessions.host import session_for

        opened, owned = session_for(resolved, credential=credential), True

    try:
        with opened.workflow(new_workflow_id()) as workflow_id:
            token = _ACTIVE.set(
                Workflow(workspace=resolved, session=opened, workflow_id=workflow_id)
            )
            try:
                yield _ACTIVE.get()
            finally:
                _ACTIVE.reset(token)
    finally:
        if owned:
            opened.close()


def _inherited(session) -> "Workspace | None":
    """The configuration an operation on ``session`` starts from."""

    active = active_workflow()
    if active is not None and (session is None or session is active.session):
        return active.workspace
    return getattr(session, "workspace", None)


def workflow_session(session: "Session | None") -> "Session | None":
    """``session``, or the active workflow's when none is given."""

    if session is not None:
        return session
    active = active_workflow()
    return None if active is None else active.session


__all__ = ["Workflow", "active_workflow", "workflow", "workflow_session"]
