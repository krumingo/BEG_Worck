"""Pure, standard-library-only target validation for the isolated W0-02 run.

Never import application packages, Motor, PyMongo or dotenv here. Expected
values are literals. Error messages deliberately do not echo possible secrets.
"""
import os
import sys
from types import MappingProxyType

VALIDATION_ENV = MappingProxyType({
    "MONGO_URL": "mongodb://begwork-w002-testmongo:27017",
    "DB_NAME": "w002_op_test",
    "BEG_SYSTEM_DB": "w002_sys_test",
})


def validation_problems(mongo_url, db_name, sys_db):
    actual = (mongo_url, db_name, sys_db)
    return [f"{name}: missing or not the sanctioned validation value"
            for name, value in zip(VALIDATION_ENV, actual)
            if not isinstance(value, str) or value != VALIDATION_ENV[name]]


def require_validation_env(mongo_url, db_name, sys_db, *, exit_code=3):
    problems = validation_problems(mongo_url, db_name, sys_db)
    if problems:
        print("FAIL-CLOSED (W0-02 validation): " + "; ".join(problems), file=sys.stderr)
        raise SystemExit(exit_code)


def require_runtime_env(env=None):
    env = os.environ if env is None else env
    require_validation_env(*(env.get(k, "") for k in VALIDATION_ENV))
    return {k: env[k] for k in VALIDATION_ENV}
