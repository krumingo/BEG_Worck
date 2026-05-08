# BEG_Work — Resource & Cost Model
# Generated: 2026-04-10

## 1. Personnel Types

### Direct
- Works directly on project/SMR
- Hours, labor, insurance → charged to project
- Insurance follows worker → project cost
- Example: Mason, Plasterer, Electrician

### Overhead
- 100% overhead personnel
- Cost goes to overhead pool, NOT to any project directly
- Insurance → overhead pool
- Example: Secretary, Office cleaner, Part of warehouse admin

### Hybrid
- Part of time on project, part overhead
- Split proportionally: project_hours / total_hours
- Insurance splits the same way
- Example: Driver (4h delivery to site + 4h general), Warehousekeeper, Procurer
- Has `utilization_target_pct` (default 50%) for planning

## 2. Subcontractor Types

### Company (external firm)
- We pay by invoice
- NO personal insurance burden (they handle their own)
- NO admin burden for their personnel
- Carries SMALL overhead weight: 0.30× (coordination, quality control)
- Total loaded cost = invoice × (1 + 0.30)

### Crew (external brigade)
- We may have internal burden:
  - Hiring/documents/admin
  - Social contributions (if applicable)
  - Administrative labor
- Carries HIGHER overhead weight: 0.60×
- Insurance burden: YES (if we process their paperwork)
- Total loaded cost = invoice × (1 + 0.60) + insurance

## 3. Overhead Pools

| Pool | What goes in | Allocation basis |
|------|-------------|-----------------|
| Administration | Office rent, accounting, legal, management salaries | by_revenue or equal_split |
| Base/Warehouse | Warehouse rent, warehouse staff, storage | by_materials or by_deliveries |
| Transport | Vehicles, fuel, driver overhead hours | by_km or by_deliveries |
| General | Insurance, miscellaneous, utilities | by_person_days or equal_split |

## 4. Allocation Rules

| Rule | Formula | Use case |
|------|---------|----------|
| by_hours | pool_cost × (project_hours / total_hours) | Labor-intensive projects |
| by_person_days | pool_cost × (project_person_days / total_person_days) | General allocation |
| by_km | pool_cost × (project_km / total_km) | Transport pool |
| by_deliveries | pool_cost × (project_deliveries / total_deliveries) | Warehouse pool |
| by_materials | pool_cost × (project_materials_cost / total_materials_cost) | Material-heavy projects |
| by_revenue | pool_cost × (project_revenue / total_revenue) | Revenue-based allocation |
| equal_split | pool_cost / active_projects_count | Simple equal split |
| manual_percent | pool_cost × manually_set_percent | Manual override |

## 5. Insurance Treatment

| Resource Type | Insurance Target | Rule |
|--------------|-----------------|------|
| Direct | Project (follows worker) | Insurance cost = clean_labor × 32.8% → direct to project |
| Overhead | Overhead pool | Insurance cost → same pool as the worker |
| Hybrid | Mixed (proportional) | Insurance splits same ratio as direct/overhead hours |
| Subcontractor Company | None (external) | No insurance from us |
| Subcontractor Crew | May apply | If we handle paperwork → insurance as admin burden |

## 6. Default Burden Weights (editable per org)

| Type | Weight | Meaning |
|------|--------|---------|
| own_labor | 1.00 | Full cost (clean + insurance + overhead allocation) |
| subcontractor_company | 0.30 | 30% overhead for coordination/QC |
| subcontractor_crew | 0.60 | 60% overhead for admin/insurance/coordination |
| mixed_execution | 0.60 | When own + sub work together |

## 7. Employee Profile Fields (additive)

New optional fields on employee_profiles:
- `resource_type`: "direct" | "overhead" | "hybrid" (default: "direct")
- `default_overhead_pool`: "administration" | "base_warehouse" | "transport" | "general"
- `allocation_rule`: "by_hours" | "by_person_days" | ... (default: "by_hours")
- `insurance_mode`: "follows_worker" | "overhead_pool" | "mixed"
- `utilization_target_pct`: number (for hybrid, default: 50)

## 8. API Endpoints

- GET /resource-model/config — org config
- PUT /resource-model/config — update config (admin)
- GET /resource-model/enums — all valid values
- GET /resource-model/classify-worker/{id} — classify a worker
- GET /resource-model/classify-subcontractor/{type} — classify a subcontractor
- POST /resource-model/worker-cost-preview — compute full cost breakdown
- POST /resource-model/subcontractor-burden-preview — compute subcontractor burden
