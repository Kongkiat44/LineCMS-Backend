from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import os, pprint

#Database connection string
MONGODB_CLIENTSTR = os.getenv("MONGODB_CLIENTSTR")

#Function to create new client to connect MongoDB
def getdbclient():
    return MongoClient(MONGODB_CLIENTSTR)


#Function to test connection by send a ping to database
def isconnect(dbclient:MongoClient):
    try:
        dbclient.admin.command('ping')    
    except Exception as e:
        return False, str(e)
    return True, 'successfully connect to MongoDB'

