# Module Design Guidelines

How to decide *where* new data collection belongs and *what* to name the module.
The goal is to keep the number of modules small and their scope stable as coverage grows.

## 1. Decide which module the data belongs to

Classify by **what kind of data it is** and **how accounts/regions are selected** (the
collection topology), not by which dashboard consumes it.

| Data kind | Goes to | Notes |
|---|---|---|
| **Inventory** — `describe_*` / `list_*` of live customer resources, per linked account | `module-inventory` | Add a new entry to the `AwsObjects` fan-out. Don't create a new module. |
| **Reference** — catalogs *not* tied to a specific customer resource (engine versions, EOL/lifecycle dates, region/service availability, instance-type metadata) | `module-reference` | Collected in the data-collection account only. |
| **Service-specific** — metrics, operational or lifecycle API calls for one service (CloudWatch metrics, pending maintenance, recommendations, …) | `module-<service>` | One module per service. See §2. |
| **Derived** — anything computed by joining datasets above | An Athena `NamedQuery` **view** | Never a *new module*. See §1.1 for the narrow case where a module derives in-Lambda. |

If the data can be produced by joining tables that already exist, it is **derived** — write a
view. Collect raw data once; compute in Athena.

### 1.1 When a module may derive in-Lambda

"Derived → view" is about **not standing up new collection** for something already joinable. It
does not mean a module is forbidden to emit a computed object. A module may compute and emit a
derived object when **all** of the following hold:

1. **The derivation is not expressible as a reasonable Athena view.** Iterative or graph
   computations — transitive closure, connected components, stable hashing of a component's
   members — are the clear case. A join, filter, aggregation, or window function is *not*: write
   the view.
2. **Its inputs are the module's own in-run records, not other modules' tables.** If the
   computation reaches across module boundaries, it is a view over published tables, because the
   module has no guarantee about another module's freshness or partition state.
3. **The inputs are collected in the same invocation anyway,** so deriving adds no new API calls
   and no new IAM surface — only CPU and an extra output prefix.
4. **The result is emitted as its own object** (its own S3 prefix and Glue table), not folded into
   an inventory record, so raw and derived data stay separable and the raw data remains queryable
   on its own.

When these hold, deriving in-Lambda is preferred over a view: the module already holds the whole
graph in memory for one account, whereas a view would have to reconstruct it in SQL across
partitions.

`module-media-services` is the reference example. Its `workflow_tracing` object walks
resource-to-resource references collected across MediaLive, MediaPackage, MediaTailor, S3, and
CloudFront, finds connected components, and assigns each a stable `workflow_id` — connected
components are not something to write in Athena SQL. Its `cost_optimization` object applies
per-service threshold rules to those same in-run records plus the CloudWatch metrics collected
alongside them.

The rule this replaces the old absolute with: **derived data does not justify a new module, and it
does not justify new collection.** It may justify a new *object* inside a module that is already
collecting the inputs.

## 2. Service-specific modules: default to `module-<service>`

- **Default to one generic module per service** (`module-rds`, `module-workspaces`), holding
  *all* of that service's service-specific collection. Grow it by adding internal objects,
  the way `module-inventory` grew to many objects under one stack — the module count stays
  flat as scope increases.
- **Add a `-<facet>` suffix only when a hard boundary forces a separate stack**, i.e. the
  **collection topology differs**:
  - LINKED (cross-account member roles) vs. data-collection-account-only vs.
    management/payer-only vs. EUC account enumeration;
  - a facet that needs its own opt-in toggle;
  - an incompatible IAM boundary.

  A facet suffix is **not** justified by "the data is conceptually different" or "cleaner
  code" alone. Within one topology, consolidate.

- **Do not name a module after a verdict or a single API.** Avoid `health`, `optimization`,
  `compliance` (verdicts) and `metrics`, `usage`, `maintenance` (single facets) — they
  re-narrow a module that should stay generic. This constrains the **module** name only;
  objects *inside* a module may be named for what they are (`cost_optimization`,
  `cloudwatch_metrics`), since they do not bound the module's scope.

- **A domain of services may share one module** when the services are only useful together and
  the topology is identical. `module-media-services` covers MediaLive, MediaPackage,
  MediaConvert, MediaConnect, MediaTailor, and IVS — plus the CloudFront distributions and S3
  buckets those workflows depend on — because a media workflow spans several of them at once and
  the value is in the workflow, not the individual service. Splitting it per service would force
  every consumer to reassemble the workflow across six tables.

  This is a deliberate exception, not the default. Justify it the same way §2 justifies a facet
  suffix: point at a hard reason. "These services are in the same console category" is not one.
  Where such a module reaches into a shared service, it collects only the resources its own
  workflows reference — `module-media-services` emits media-associated S3 buckets, leaving
  general bucket inventory to `module-inventory` — so it does not duplicate another module's
  coverage.

- **Legacy exceptions are grandfathered.** `module-rds-usage` (RDS CloudWatch metrics) and
  `module-workspaces-metrics` keep their names; new RDS/WorkSpaces service-specific data
  consolidates into `module-rds` / `module-workspaces`.

### Worked examples

- **RDS** — instance metrics, pending maintenance, and future RDS API calls are all plain
  LINKED topology → one `module-rds`, no further splitting. (Version/EOL catalogs →
  `module-reference`; version-compliance status → an Athena view over inventory + reference.)
- **WorkSpaces** — genuinely splits, because topology differs: inventory →
  `module-inventory` (the `EUC` object); CloudWatch metrics → its own module because EUC
  account selection and opt-in differ from a standard LINKED service.

## 3. Naming must be consistent across all touch-points

For a module, the same token must appear in the filename facet, the `Include…Module`
parameter, the `Deploy…` condition, and the nested-stack logical id.

`module-rds-usage` is the counter-example to avoid: it is `rds-usage` (file) /
`IncludeRDSUtilizationModule` (parameter) / `DeployRDSUtilizationModule` (condition) /
`RDSUsageModule` (logical id) — three different tokens for one module.

## 4. Descriptions

Name the service and the **data category**, never the specific API — so the text stays true
as scope grows.

- **Module template** (`Description:`, line 2) — generic scope + topology:
  ```
  Description: Retrieves RDS operational and configuration data across the AWS organization
  ```
- **Deploy-stack parameter** (`Include…Module`) — user-facing opt-in, with a concrete example:
  ```
  Description: Collects RDS operational details (e.g. pending maintenance) from your accounts
  ```

Avoid the words `health`, `metrics`, `usage`, `utilization` in descriptions of generic
modules for the same reason as in names.

## 5. Wiring a new service-specific module

A new module must be registered in the deploy stacks following the existing contract:

- **`deploy/deploy-data-collection.yaml`**: `Include<Name>Module` parameter (+ `ParameterGroups`
  / `ParameterLabels` entries), a `Deploy<Name>Module` condition, and a nested
  `<Name>Module` `AWS::CloudFormation::Stack` gated on that condition.
- **`deploy/deploy-in-linked-account.yaml`** (for LINKED collection): matching
  `Include<Name>ModulePolicy` condition, a least-privilege `AWS::IAM::Policy`, and the
  assume-role trust for `${ResourcePrefix}<name>-LambdaRole`.
- **`deploy/deploy-in-management-account.yaml`**: only if the module reads
  management/payer-account data. LINKED-only modules do **not** touch this stack.
