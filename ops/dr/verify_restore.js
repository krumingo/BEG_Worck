// W0-10A — verification of a restored backup, run by mongosh against the ISOLATED instance.
//
//   mongosh --host <temp-container> --quiet --file /verify.js
//
// Prints one JSON object. The scalar summary keys come first, because the runner reads them
// with sed rather than a JSON parser. `ok` is false whenever an expectation is not met; the
// process still exits 0 so the runner can read the reasons. A hard failure (no connection)
// exits 1.
//
// Checks: expected databases present · collection inventory with document counts · every
// collection carries its _id index · representative documents are readable · tenant fields
// are enumerable where the schema has them.

const EXPECTED_DBS = ["begwork_beg", "begwork_system"];
const SYSTEM_DBS = ["admin", "config", "local"];
const TENANT_FIELDS = ["tenant_id", "org_id"];
const SAMPLE_LIMIT = 5;      // largest collections to read a document from
const TENANT_SAMPLE = 2000;  // bounded scan for distinct tenant values

const out = {
  ok: true,
  total_databases: 0,
  total_collections: 0,
  total_documents: 0,
  collections_without_id_index: 0,
  sample_reads_failed: 0,
  tenant_check: "NOT_APPLICABLE",
  generated_at: new Date().toISOString(),
  problems: [],
  expected_databases: EXPECTED_DBS,
  missing_databases: [],
  unexpected_databases: [],
  tenant_fields_found: [],
  samples: [],
  databases: [],
};

function problem(msg) {
  out.ok = false;
  out.problems.push(msg);
}

let dbNames;
try {
  dbNames = db
    .adminCommand({ listDatabases: 1, nameOnly: true })
    .databases.map((d) => d.name)
    .filter((n) => SYSTEM_DBS.indexOf(n) === -1);
} catch (e) {
  print(JSON.stringify({ ok: false, fatal: String(e) }));
  quit(1);
}

out.total_databases = dbNames.length;
out.missing_databases = EXPECTED_DBS.filter((n) => dbNames.indexOf(n) === -1);
out.unexpected_databases = dbNames.filter((n) => EXPECTED_DBS.indexOf(n) === -1);
if (out.missing_databases.length > 0) {
  problem("expected database(s) missing after restore: " + out.missing_databases.join(", "));
}

const allCollections = []; // {db, name, documents}

for (const dbName of dbNames) {
  const target = db.getSiblingDB(dbName);
  const entry = { name: dbName, collections: [] };
  let names;
  try {
    names = target.getCollectionNames();
  } catch (e) {
    problem("cannot list collections of " + dbName + ": " + e);
    out.databases.push(entry);
    continue;
  }
  for (const collName of names) {
    const coll = target.getCollection(collName);
    const info = { name: collName, documents: null, indexes: [] };
    try {
      info.documents = coll.countDocuments({});
      out.total_documents += info.documents;
    } catch (e) {
      problem("cannot count " + dbName + "." + collName + ": " + e);
    }
    try {
      info.indexes = coll.getIndexes().map((i) => i.name);
    } catch (e) {
      problem("cannot read indexes of " + dbName + "." + collName + ": " + e);
    }
    if (info.indexes.indexOf("_id_") === -1) {
      out.collections_without_id_index += 1;
      problem("no _id index on " + dbName + "." + collName);
    }
    entry.collections.push(info);
    allCollections.push({ db: dbName, name: collName, documents: info.documents || 0 });
    out.total_collections += 1;
  }
  out.databases.push(entry);
}

// ---- representative reads: the largest collections must hand back a real document
const largest = allCollections
  .filter((c) => c.documents > 0)
  .sort((a, b) => b.documents - a.documents)
  .slice(0, SAMPLE_LIMIT);

for (const c of largest) {
  const sample = { db: c.db, collection: c.name, documents: c.documents, readable: false };
  try {
    const doc = db.getSiblingDB(c.db).getCollection(c.name).findOne({});
    sample.readable = doc !== null && doc !== undefined && doc._id !== undefined;
    sample.fields = doc ? Object.keys(doc).length : 0;
  } catch (e) {
    sample.error = String(e);
  }
  if (!sample.readable) {
    out.sample_reads_failed += 1;
    problem("sample read failed for " + c.db + "." + c.name);
  }
  out.samples.push(sample);
}

if (largest.length === 0) {
  problem("no non-empty collection found — a restore of an empty dataset proves nothing");
}

// ---- tenant separation: where the schema carries a tenant field, values must be enumerable
const tenantReport = [];
for (const c of allCollections) {
  if (c.documents === 0) continue;
  let doc;
  try {
    doc = db.getSiblingDB(c.db).getCollection(c.name).findOne({});
  } catch (e) {
    continue;
  }
  if (!doc) continue;
  for (const field of TENANT_FIELDS) {
    if (doc[field] === undefined) continue;
    if (out.tenant_fields_found.indexOf(field) === -1) out.tenant_fields_found.push(field);
    try {
      const values = db
        .getSiblingDB(c.db)
        .getCollection(c.name)
        .aggregate([{ $limit: TENANT_SAMPLE }, { $group: { _id: "$" + field } }, { $limit: 50 }])
        .toArray()
        .map((r) => r._id);
      tenantReport.push({
        db: c.db,
        collection: c.name,
        field: field,
        distinct_values_in_sample: values.length,
        nulls_present: values.indexOf(null) !== -1,
      });
    } catch (e) {
      problem("tenant scan failed for " + c.db + "." + c.name + "." + field + ": " + e);
    }
  }
}
out.tenant_report = tenantReport;

if (tenantReport.length === 0) {
  out.tenant_check = "NOT_APPLICABLE";
} else if (tenantReport.every((r) => r.distinct_values_in_sample > 0)) {
  out.tenant_check = "PASS";
} else {
  out.tenant_check = "FAIL";
  problem("a tenant field yielded no values in its sample");
}

print(JSON.stringify(out, null, 2));
quit(0);
