/*
Table ID: _.ColumnDataType

Description: >-
  SQL-endpoint columns of installed tables and views, refreshed after Build.

Lineage: >-
  Read from sys.columns on each installed SQL endpoint after Build.

Dependencies: []

Has load procedure: false
Static: true

Primary key: Item type, Item name, Schema name, Object name, Column name

Not null:
  - Column ordinal
  - Data type
  - Is nullable
  - Signature

Schema:
  Item type: varchar(128)
  Item name: varchar(128)
  Schema name: varchar(128)
  Object name: varchar(128)
  Column name: varchar(128)
  Column ordinal: bigint
  Data type: varchar(128)
  Max length: bigint
  Numeric precision: bigint
  Numeric scale: bigint
  Is nullable: bit
  Is identity: bit
  Signature: varchar(128)

Column notes:
  Item type: Logical Weaver item type.
  Item name: Logical Weaver item name.
  Schema name: The object's schema, including its Lakehouse area.
  Object name: The object's name.
  Column name: The SQL column name.
  Column ordinal: The SQL column ordinal.
  Data type: The SQL data type.
  Max length: Maximum bytes; -1 denotes max.
  Numeric precision: SQL numeric precision.
  Numeric scale: SQL numeric or temporal scale.
  Is nullable: Whether SQL permits nulls.
  Is identity: Whether SQL generates identity values.
  Signature: Content hash of the observed column schema.
*/
select cast(null as varchar(128)) as [Item type]
     , cast(null as varchar(128)) as [Item name]
     , cast(null as varchar(128)) as [Schema name]
     , cast(null as varchar(128)) as [Object name]
     , cast(null as varchar(128)) as [Column name]
     , cast(null as bigint) as [Column ordinal]
     , cast(null as varchar(128)) as [Data type]
     , cast(null as bigint) as [Max length]
     , cast(null as bigint) as [Numeric precision]
     , cast(null as bigint) as [Numeric scale]
     , cast(null as bit) as [Is nullable]
     , cast(null as bit) as [Is identity]
     , cast(null as varchar(128)) as [Signature]
 where 1 = 0
