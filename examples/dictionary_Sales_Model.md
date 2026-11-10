# Data dictionary — Sales Model
Workspace: Finance WS · run 2026-11-10 23:58 UTC
Hidden objects are marked *(hidden)*. Descriptions shown as `—` are missing.

## Relationships

| From | To | Cardinality | Cross Filter | Active |
|---|---|---|---|---|
| Sales[ProductKey] | Product[ProductKey] | many-to-one | OneDirection | yes |
| Sales[DateKey] | Date[DateKey] | many-to-one | OneDirection | yes |

## Date — Date dimension

—


| Column Name | Data Type | Hidden | Desc |
|---|---|---|---|
| DateKey | Int64 |  | — |
| MonthName | Int64 |  | — |
| MonthNo | Int64 | yes | — |
| Fiscal Year | Int64 |  | — |
| Fiscal Quarter | Int64 |  | — |

**Power Query (`Date`)**
```powerquery
let
  Source = Sql.Database("x","y")
in Source
```

## Fields — Field parameter

—


| Column Name | Data Type | Hidden | Desc |
|---|---|---|---|
| Fields | Int64 |  | — |
| Fields Fields | Int64 | yes | — |
| Fields Order | Int64 | yes | — |

**Calculated table expression**
```dax
{("Total", NAMEOF('_Measures'[Param Measure]), 0)}
```

## Product — Dimension

—


| Column Name | Data Type | Hidden | Desc |
|---|---|---|---|
| ProductKey | Int64 | yes | — |
| Name | Int64 |  | — |
| Color | Int64 |  | — |

**Power Query (`Product`)**
```powerquery
let
  Source = Sql.Database("x","y")
in Source
```

## Sales — Fact

—


| Column Name | Data Type | Hidden | Desc |
|---|---|---|---|
| ProductKey | Int64 | yes | — |
| DateKey | Int64 | yes | — |
| Amount | Int64 |  | — |
| Notes | Int64 |  | — |

**Power Query (`Sales`)**
```powerquery
let
  Source = Sql.Database("x","y")
in Source
```

**Calculated column `Margin`**: —
```dax
Sales[Amount] * 0.2
```

## Store — Disconnected

—


| Column Name | Data Type | Hidden | Desc |
|---|---|---|---|
| Name | Int64 |  | — |
| Address | Int64 |  | — |

**Power Query (`Store`)**
```powerquery
let
  Source = Sql.Database("x","y")
in Source
```

## _Measures — Measure table

—


| Column Name | Data Type | Hidden | Desc |
|---|---|---|---|
| Column1 | Int64 | yes | — |

**Power Query (`_Measures`)**
```powerquery
let
  Source = Sql.Database("x","y")
in Source
```

### [Param Measure]

—

```dax
SUM(Sales[Notes])
```

### [Total Sales]

Sum

```dax
SUM(Sales[Amount])
```

### [Unused] *(hidden)*

—

```dax
COUNTROWS(Sales)
```

## Shared Power Query expressions and parameters

**`ServerName`**: —
```powerquery
"srv" meta [IsParameterQuery=true]
```
