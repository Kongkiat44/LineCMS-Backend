from datetime import datetime
from pymongo.errors import ConnectionFailure
from pymongo.mongo_client import MongoClient
import linecms_database
import os
from backend import app

SAVE_FACE_PATH = os.getenv("SAVE_FACE_PATH")
SAVE_IMAGE_PATH = os.getenv("SAVE_IMAGE_PATH")
SAVE_FILE_PATH = os.getenv("SAVE_FILE_PATH")
SAVE_GRAPH_PATH = os.getenv("SAVE_GRAPH_PATH")
DATABASE_NAME = os.getenv("DATABASE_NAME")

def get_database() -> MongoClient:
    try:
        linecms_database.getdbclient()
    except ConnectionFailure as e:
        app.logger.info("Failed to connect to database from schedule_leftgroup.py, reconnecting... \nFailure message: %s\n" % e)
    return linecms_database.getdbclient()

def check_left_group() -> None:
    current_time = datetime.now()

    db_client = get_database()
    database = db_client[DATABASE_NAME]
    col_groups = database.Groups
    col_images = database.Images
    col_faces = database.Faces
    col_clusters = database.Clusters
    col_graphs = database.Graphs
    col_logs = database.Logs
    col_files = database.Files
    #deleted_groups_data = []

    for group in col_groups.find({"status":"Deleted"}):
        #deleted_groups_data.append(group)
        #groupId = group["_id"]
        image_counts = group["image_count"]
        left_time = group["last_used"]
        difference_time = current_time - left_time

        #Delete group data if chat bot left the group more than 3 days
        #difference_time.days >= 3
        #temporary condition for testing code : difference_time.seconds >= 60 (left more than 60 seconds)
        #difference_time.seconds >= 300
        #difference_time.days >= 3
        if difference_time.seconds >= 180: # Demo: test in 3 minutes
            
            for image in col_images.find({"group_id":group["_id"]}):
                image_name = image["_id"]

                #Delete face from file server and database
                if col_faces.find_one(filter={"image_link":image_name}) is not None:
                    face = col_faces.find_one_and_delete(filter={"image_link":image_name})
                    face_name = face["_id"]
                    os.remove(path=SAVE_FACE_PATH+face_name)
                
                #Delete image from file server and database
                col_images.delete_one(filter={"_id":image_name})
                os.remove(path=SAVE_IMAGE_PATH+image_name)
                image_counts -= 1
            
            #Delete files from database
            for file in col_files.find({"group_id":group["_id"]}):
                fileName = file["_id"]
                os.remove(path=SAVE_FILE_PATH+fileName)
            col_files.delete_many(filter={"group_id":group["_id"]})

            #Delete graph(s) data from database
            for graph in col_graphs.find({"group_id":group["_id"]}):
                graphName = graph["_id"]
                os.remove(path=SAVE_GRAPH_PATH+graphName)
            col_graphs.delete_many(filter={"group_id":group["_id"]})

            #Delete cluster(s) data from database
            col_clusters.delete_many(filter={"group_id":group["_id"]})

            #Raise exception message to notify that there is unexpected issue happened
            if image_counts != 0:
                raise Exception("After deletes all images, variable image_count doesn't equal to zero.\nGroup id: %s" % group["_id"])
            else:
                col_groups.delete_one(filter={"_id":group["_id"]})

            #Log delete group data in database
            log_data = {
                "type": "Official",
                "related_to": group["_id"],
                "content": "The data of group id {gid} has deleted from the server".format(gid=group["_id"]),
                "saved_time": datetime.now(),
            }
            col_logs.insert_one(log_data)
            

#Start the function when run this python file
if __name__ == "__main__":
    check_left_group()