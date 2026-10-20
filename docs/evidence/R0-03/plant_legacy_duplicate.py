"""R0-03 bot test, step 5 only — plant ONE pre-R0-03-style duplicate in the disposable LOCAL DB.

Before R0-03 the same email could exist in two firms. The API can no longer create that, so
the runner copies firm B's Ivan into firm A with a different spelling (`` Ivan@R003B.test``),
the way old data may look. Refuses anything but 127.0.0.1/localhost.

    python plant_legacy_duplicate.py mongodb://127.0.0.1:27019/?directConnection=true r003_bot seed.json
"""
import json
import sys
import uuid
from urllib.parse import urlparse

from pymongo import MongoClient

url, db_name, seed_path = sys.argv[1:4]
assert urlparse(url).hostname in ("127.0.0.1", "localhost"), "local disposable database only"
seed = json.load(open(seed_path))
db = MongoClient(url)[db_name]
ivan = db.users.find_one({"id": seed["ivan_b"]["id"]}, {"_id": 0})
twin = dict(ivan, id=str(uuid.uuid4()), org_id=seed["org_a"], email=" Ivan@R003B.test")
db.users.insert_one(twin)
print(json.dumps({"planted_user_id": twin["id"], "org_id": twin["org_id"]}))
