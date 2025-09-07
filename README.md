# kover

![Build Status](https://img.shields.io/github/actions/workflow/status/megawattka/kover/actions.yml)
![License](https://img.shields.io/github/license/megawattka/kover)
![Python - Req](https://img.shields.io/badge/python-3.10+-blue)
![Pypi Status](https://img.shields.io/pypi/status/kover)
![Last Commit](https://img.shields.io/github/last-commit/megawattka/kover)
![MongoDB](https://img.shields.io/badge/MongoDB-6.0+-green)

**Kover** is a model-orientied strictly typed mongodb object-document mapper (ODM) supporting local and remote servers.<br>
This library was inspired by <a href=https://github.com/sakal/aiomongo>this project</a> i like it very much. Though its 9 years old.
Kover is linted by Ruff and supports pyright strict type checking mode.

```py
import asyncio

from kover import AuthCredentials, Kover


async def main():
    # or AuthCredentials.from_environ()
    # (requires MONGO_USER and MONGO_PASSWORD environment variables)
    # (remove if no auth present)
    credentials = AuthCredentials(username="<username>", password="<password>")
    client = await Kover.make_client(credentials=credentials)
    # OR
    client = await Kover.from_uri("mongodb://user:pass@host:port?tls=false")

    found = await client.db.test.find().limit(10).to_list()
    print(found)

if __name__ == "__main__":
    asyncio.run(main())
```

The main reason why i created this project is that Motor - official async wrapper for mongodb, uses ThreadPool executor and it's just a wrapper around pymongo. In general thats slower than clear asyncio and looks more dirty.
- 02.12.24 UPDATE: pymongo added async support but its kinda messed up. pymongo's code looks complicated, dirty and unclean.

# Dependencies
- All platforms.
- python 3.10+
- MongoDB 6.0+ (not sure about older versions)
- pydantic 2.10.6 or later
- dnspython 2.7.0 or later

# Features
Almost all features from pymongo. All auth types are supported. Integration with Pydantic supported.
this lib was built for new mongod versions. All features that were marked as DEPRECATED in docs
were NOT added. See docs for references. The kover.bson package was entirely copied from pymongo source code. I do not own these files.

### Cursors
if you just need list:

```py
items = await db.test.find().limit(1000).batch_size(50).to_list()
```

### or
```py
async with db.test.find().limit(1000).batch_size(50) as cursor:
    async for item in cursor:
        print(item)
```
### if collection has specific schema:
```py
from kover import Document

class User(Document):
    uuid: UUID
    name: str
    age: int


async with db.test.find(cls=User).limit(1000) as cursor:
    async for item in cursor:
        print(item) # its now User

```
# See more examples in ./examples folder.

# If you found a bug, open an issue please, or even better create a pull request, thx ❤️