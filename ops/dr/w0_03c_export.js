// W0-03C — export of exactly the fields the Master Data duplicate report needs, from every
// non-system database of the ISOLATED restored instance of W0-10A.
//
//   mongosh --host <temp-container> --quiet --file /w003c_export.js > export.sensitive.json
//
// Read-only: find() with a projection, nothing else. Only the collections and fields of the
// plan below are read — no IBAN, no address, no document body. The plan is a copy of
// backend/app/master_data/uniqueness.py:export_plan() and a test keeps the two identical,
// so the report can never judge a field this export left out.
//
// The output still holds raw identifiers (ЕИК, ЕГН), so the hook writes it mode 600 and
// deletes it as soon as the report exists. The report masks ЕГН.

// BEGIN EXPORT PLAN
const PLAN = {
  "canonical": {
    "md_activity": [
      "aliases.normalized",
      "display_name",
      "entity_type",
      "id",
      "raw_value",
      "status",
      "tenant_id"
    ],
    "md_asset_type": [
      "aliases.normalized",
      "display_name",
      "entity_type",
      "id",
      "raw_value",
      "status",
      "tenant_id"
    ],
    "md_item": [
      "aliases.normalized",
      "display_name",
      "entity_type",
      "id",
      "identifiers.key",
      "raw_value",
      "status",
      "tenant_id"
    ],
    "md_location": [
      "aliases.normalized",
      "display_name",
      "entity_type",
      "id",
      "raw_value",
      "status",
      "tenant_id"
    ],
    "md_organization": [
      "aliases.normalized",
      "display_name",
      "entity_type",
      "id",
      "identifiers.key",
      "raw_value",
      "status",
      "tenant_id"
    ],
    "md_pending_mapping": [
      "display_name",
      "entity_type",
      "id",
      "normalized_value",
      "raw_value",
      "status",
      "tenant_id"
    ],
    "md_person": [
      "aliases.normalized",
      "display_name",
      "entity_type",
      "id",
      "identifiers.key",
      "raw_value",
      "status",
      "tenant_id"
    ],
    "md_physical_asset": [
      "aliases.normalized",
      "display_name",
      "entity_type",
      "id",
      "identifiers.key",
      "raw_value",
      "status",
      "tenant_id"
    ],
    "md_tag": [
      "aliases.normalized",
      "display_name",
      "entity_type",
      "id",
      "normalized_name",
      "raw_value",
      "status",
      "tenant_id"
    ],
    "md_unit": [
      "aliases.normalized",
      "display_name",
      "entity_type",
      "id",
      "normalized_name",
      "raw_value",
      "status",
      "tenant_id"
    ]
  },
  "legacy": {
    "asset_units": [
      "id",
      "inventory_no",
      "org_id",
      "qr_id",
      "serial_no"
    ],
    "clients": [
      "companyName",
      "eik",
      "id",
      "name",
      "org_id",
      "vat_number"
    ],
    "companies": [
      "companyName",
      "eik",
      "id",
      "name",
      "org_id",
      "vat_number"
    ],
    "counterparties": [
      "companyName",
      "eik",
      "id",
      "name",
      "org_id",
      "vat_number"
    ],
    "items": [
      "id",
      "name",
      "org_id",
      "sku"
    ],
    "persons": [
      "egn",
      "first_name",
      "id",
      "last_name",
      "org_id"
    ],
    "subcontractors": [
      "companyName",
      "eik",
      "id",
      "name",
      "org_id",
      "vat_number"
    ]
  },
  "schema": "beg.master-data-uniqueness-export/v1"
};
// END EXPORT PLAN

const SYSTEM_DBS = ["admin", "config", "local"];
const out = {
  schema: PLAN.schema,
  exported_at: new Date().toISOString(),
  scanned_databases: [],
  databases: {},
};

let dbNames;
try {
  dbNames = db
    .adminCommand({ listDatabases: 1, nameOnly: true })
    .databases.map((d) => d.name)
    .filter((n) => SYSTEM_DBS.indexOf(n) === -1)
    .sort();
} catch (e) {
  print(JSON.stringify({ ok: false, fatal: String(e) }));
  quit(1);
}

const wanted = Object.assign({}, PLAN.canonical, PLAN.legacy);
for (const dbName of dbNames) {
  out.scanned_databases.push(dbName);
  const target = db.getSiblingDB(dbName);
  const present = target.getCollectionNames();
  const body = { collections: {} };
  for (const coll of Object.keys(wanted).sort()) {
    if (present.indexOf(coll) === -1) continue;
    const projection = { _id: 0 };
    for (const f of wanted[coll]) projection[f] = 1;
    body.collections[coll] = target.getCollection(coll).find({}, projection).toArray();
  }
  if (Object.keys(body.collections).length > 0) out.databases[dbName] = body;
}

print(EJSON.stringify(out, { relaxed: true }));
