"""Demo only: create_company.py does not create a subscription (README §6), so the
harness inserts an `enterprise` subscription directly into the disposable demo DB."""
import datetime
import uuid

import pymongo

c = pymongo.MongoClient("mongodb://127.0.0.1:27161/?directConnection=true")
print(c.list_database_names())
db = c.demoint_begwork
org = db.organizations.find_one({}, {"_id": 0, "id": 1, "name": 1})
print(org)
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
if not db.subscriptions.find_one({"org_id": org["id"]}):
    db.subscriptions.insert_one({"id": str(uuid.uuid4()), "org_id": org["id"], "plan_id": "enterprise",
                                 "status": "active", "created_at": now, "updated_at": now})
print("subscriptions:", db.subscriptions.count_documents({}))
