from pymongo import AsyncMongoClient, MongoClient

from ssw.config import LS_MONGODB_URI

async_mongo_client = AsyncMongoClient(LS_MONGODB_URI)
mongo_client = MongoClient(LS_MONGODB_URI)