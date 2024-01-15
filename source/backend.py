from flask import Flask, request, abort, jsonify
#import ngrok
import json, os, requests
import time
import hashlib
import random, string
import linecms_database
from bson.objectid import ObjectId
from pymongo.mongo_client import MongoClient
#from pymongo.errors import ConnectionFailure
from datetime import datetime

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, ImageMessage, PushMessageRequest
)
from linebot.v3.webhooks import (MessageEvent, TextMessageContent, ImageMessageContent,
    JoinEvent, LeaveEvent, MemberJoinedEvent, MemberLeftEvent, UnsendEvent, FollowEvent, 
    UnfollowEvent, PostbackEvent, FileMessageContent
)


app = Flask(__name__)

BOT_ACCESS_TOKEN = os.getenv("BOT_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
SAVE_GROUPPROFILE_PATH = os.getenv("SAVE_GROUPPROFILE_PATH")
SAVE_GRAPH_PATH = os.getenv("SAVE_GRAPH_PATH")
SAVE_FACE_PATH = os.getenv("SAVE_FACE_PATH")
SAVE_IMAGE_PATH = os.getenv("SAVE_IMAGE_PATH")
SAVE_FILE_PATH = os.getenv("SAVE_FILE_PATH")
MODEL_SERVER_IMAGE_LINK = os.getenv("MODEL_SERVER_IMAGE_LINK")
MODEL_SERVER_OTHER_LINK = os.getenv("MODEL_SERVER_OTHER_LINK")
MODEL_SERVER_GRAPH_LINK = os.getenv("MODEL_SERVER_GRAPH_LINK")
TEMP_SERVER_URL = os.getenv("TEMP_SERVER_URL")


configuration = Configuration(access_token=BOT_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

api_client = ApiClient(configuration)
line_bot_api = MessagingApi(api_client)

save_data_on_db = True
is_mongoDB_connect = False
db_client = None

#Temporary global variable for test database insert/update/delete json data
DATABASE_NAME = os.getenv("DATABASE_NAME")
database = None
col_groups = None
col_images = None
col_users = None
col_faces = None
col_graphs = None
col_clusters = None
col_logs = None
col_files = None


# ### Defined function area ###

def create_bubble_menu_face(faceUrl: str, clusterId: str, groupId: str, action: str):
    if faceUrl is None or clusterId is None or groupId is None or action is None:
        return False
    #clusterId_str = str(clusterId)
    bubble_menu_dict = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": TEMP_SERVER_URL+"/linecms/face/"+faceUrl,
            "size": "240px",
            "animated": False,
            "aspectMode": "cover",
            "aspectRatio": "1:1",
            "align": "center"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "Select This Face",
                        "data": "selectFace=1&clusterId="+clusterId+"&groupId="+groupId+"&type="+action
                    },
                    "style": "primary",
                    "position": "relative",
                    "height": "sm"
                }
            ],
            "spacing": "lg",
            "position": "relative",
            "maxHeight": "75px",
            "height": "115px"
        }
    }
    return bubble_menu_dict


def create_bubble_menu_group(picUrl: str, groupName: str, groupId: str, buttonLabel: str, action: str):
    if picUrl is None or groupName is None or groupId is None or buttonLabel is None or action is None:
        return False
    
    bubble_menu_dict = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": picUrl,
            "size": "full",
            "animated": False,
            "aspectMode": "cover",
            "aspectRatio": "17:15",
            "align": "center"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": groupName,
                    "size": "xl",
                    "align": "center",
                    "weight": "regular",
                    "style": "normal",
                    "wrap": False
                },
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": buttonLabel,
                        "data": "selectGroup=1&groupId="+groupId+"&type="+action
                    },
                    "style": "primary",
                    "position": "relative",
                    "height": "sm"
                }
            ],
            "spacing": "lg",
            "position": "relative",
            "maxHeight": "130px",
            "height": "115px"
        }
    }
    return bubble_menu_dict


def create_carousel_menus_group(groupList: list, actType: str):
    bubbles_object_list = []
    for group in groupList:
        if ("groupId" not in group) or ("groupName" not in group) or ("profileLink" not in group):
            return False
        else:
            bubble_menu_dict = create_bubble_menu_group(picUrl=group["profileLink"], groupName=group["groupName"], groupId=group["groupId"], buttonLabel="Select This Group", action=actType)
            if bubble_menu_dict is False:
                return False
            else:
                bubbles_object_list.append(bubble_menu_dict)

    carousel_menus_dict = {
        "type": "flex",
        "altText": "Select Group Menus",
        "contents": {
            "type": "carousel",
            "contents": bubbles_object_list
        }
    }        
    return carousel_menus_dict


def create_carousel_menus_face(faceList: list, actType: str):
    bubbles_object_list = []
    for face in faceList:
        if ("clusterId" not in face) or ("faceFile" not in face) or ("groupId" not in face):
            return False
        else:
            bubble_menu_dict = create_bubble_menu_face(faceUrl=face["faceFile"], clusterId=face["clusterId"], groupId=face["groupId"], action=actType)
            if bubble_menu_dict is False:
                return False
            else:
                bubbles_object_list.append(bubble_menu_dict)

    carousel_menus_dict = {
        "type": "flex",
        "altText": "Select Face Menus",
        "contents": {
            "type": "carousel",
            "contents": bubbles_object_list
        }
    }        
    return carousel_menus_dict


def create_group_col_data(line_bot_api: MessagingApi, group_id: str) -> dict:
    api_response = line_bot_api.get_group_summary(group_id)
    group_summary = json.loads(api_response.to_json())
    api_response = line_bot_api.get_group_members_ids(group_id)
    group_member_ids = json.loads(api_response.to_json())

    total_ids = []
    total_ids.extend(group_member_ids["memberIds"])

    while "next" in group_member_ids:
        next_token = group_member_ids["next"]
        api_response = line_bot_api.get_group_members_ids(group_id,start=next_token)
        group_member_ids = json.loads(api_response.to_json())
        total_ids.extend(group_member_ids["memberIds"])
    
    if "pictureUrl" not in group_summary:
        group_image_link = ""
    else:
        group_image_link = group_summary["pictureUrl"]

    group_col_data = {
        "_id": group_id,
        "group_name": group_summary["groupName"],
        "group_image_link": group_image_link,
        "member_ids": total_ids,
        "status": "Active",
        "image_count": 0,
        "file_count": 0,
        "last_used": datetime.now()
    }

    return group_col_data


def create_image_col_data(imageName: str, groupId: str, messageId: str, senderId:str) -> dict:
    image_col_data = {
        "_id": imageName,
        "group_id": groupId,
        "cluster_ids": [],
        "message_id": messageId,
        "sender_id": senderId,
        "saved_time": datetime.now(),
        "updated_time": datetime.now()
    }
    return image_col_data


def create_file_col_data(localFileName: str, groupId: str, lineFileName: str, messageId: str, senderId: str) -> dict:
    file_col_data = {
        "_id": localFileName,
        "group_id": groupId,
        "file_name": lineFileName,
        "message_id": messageId,
        "sender_id": senderId,
        "saved_time": datetime.now(),
    }
    return file_col_data


def create_user_col_data(userId: str) -> dict:
    user_col_data = {
        "_id": userId,
        "status": "Active",
        "added_time": datetime.now(),
        "last_used": datetime.now()
    }
    return user_col_data

def create_log_col_data(type: str, relatedTo: str, message: str, savedTime: datetime) -> dict:
    log_data = {
        "type": type,
        "related_to": relatedTo,
        "content": message,
        "saved_time": savedTime,
    }
    return log_data


def set_db_variables(dbClient : MongoClient, dbName: str = None):
    try:
        dbClient.admin.command("ping")
    except Exception as e:
        return False, str(e)

    global database, col_users, col_groups, col_images, col_logs, col_clusters, col_faces, col_graphs, col_files
    if dbName == None:
        database = dbClient[DATABASE_NAME]
    else:
        database = dbClient[dbName]
    col_users = database.Users
    col_groups = database.Groups
    col_images = database.Images
    col_logs = database.Logs
    col_clusters = database.Clusters
    col_faces = database.Faces
    col_graphs = database.Graphs
    col_files = database.Files
    return True, ""

#Functions for handling rich menu on Line Official

def action_img_graph(action: str, userId: str) -> None:
    if action == "searchImage":
        #variables here
        log_message = "User tapped \"Search Image by Face\" menu on LineCMS official"
        action_msg = "Search Image"
        action_type = "image"
    elif action == "createRelaGraph":
        #variables here
        log_message = "User tapped \"Create Relationship Graph\" menu on LineCMS official"
        action_msg = "Create Relationship Graph"
        action_type = "graph"
    else:
        raise Exception("Incorrect action argument. arg:",action)

    #Log user tap search image by face menu on LineCMS official
    log_data = create_log_col_data("Official", userId, log_message, datetime.now())
    col_logs.insert_one(log_data)

    #Check if user is in one of the groups that also have LineCMS chat bot in it
    group_list = []
    for group in col_groups.find({"status":"Active"}):
        if userId in group["member_ids"]:
            group_data = {
                "groupId":group["_id"],
                "groupName":group["group_name"],
                "profileLink":group["group_image_link"]
            }
            group_list.append(group_data)
    
    #Send response message to user #continue here
    if len(group_list) > 12:
        #Push message to tell user to select a group
        line_bot_api.push_message(
            PushMessageRequest(
                to=userId,
                messages=[TextMessage(text="Please select the group you wish to {actmsg} from the website in this link".format(actmsg=action_msg.lower()))]
            )
        )
        #Send user to LIFF website search image page
        ""
    elif len(group_list) > 0:
        #Push message to tell user to select a group
        line_bot_api.push_message(
            PushMessageRequest(
                to=userId,
                messages=[TextMessage(text="Please select the group you wish to {actmsg} from the following menus".format(actmsg=action_msg.lower()))]
            )
        )
        #Create carousel menus and send to user
        group_carousel_menus = create_carousel_menus_group(groupList=group_list, actType=action_type)
        if group_carousel_menus is False:
            raise Exception("While processing Post Event {actmsg}, the issue was occured at creating carousel menu for group".format(actmsg=action_msg))
        else:
            url_headers = {"Authorization":"Bearer {access_token}".format(access_token=BOT_ACCESS_TOKEN), "Content-Type":"application/json"}
            carousel_menu_post_data = {
                "to": userId,
                "messages": [group_carousel_menus]
            }
            post_menu_response = requests.post(url="https://api.line.me/v2/bot/message/push", headers=url_headers, json=carousel_menu_post_data)
            if post_menu_response.status_code != 200:
                raise Exception("There was an issue occured at sending carousel menu for selecting group", post_menu_response.status_code, post_menu_response.text)
    else:
        line_bot_api.push_message(
            PushMessageRequest(
                to=userId,
                messages=[TextMessage(text="Sorry, but we could not find any groups that have you and CMS chat bot in it.\nPlease add CMS chat bot to the group for you to be able to use this option.")]
            )
        )


def res_sel_group(action_type: str, userId: str, groupId: str) -> None:
    cluster_list = []
    if action_type == "image":
        #variables here
        action_msg = "Search Image"
    elif action_type == "graph":
        #variables here
        action_msg = "Create Relationship Graph"
    else:
        raise Exception("Incorrect action type argument. arg:",action_type)
    
    #Log user choose a group to search image by face on LineCMS official
    log_message = "User chose group id {groupId} from carousel menu on LineCMS official".format(groupId=groupId)
    log_data = create_log_col_data("Official", userId, log_message, datetime.now())
    col_logs.insert_one(log_data)

    for cluster in col_clusters.find({"group_id":groupId}):
        if "face_link" in cluster:
            ### Area that might have problem with ObjectId to string ## Fix testing
            cluster_data = {
                "clusterId":str(cluster["_id"]),
                "faceFile":cluster["face_link"],
                "groupId":groupId
            }
            cluster_list.append(cluster_data)

    if len(cluster_list) > 12:
        line_bot_api.push_message(
            PushMessageRequest(
                to=userId,
                messages=[TextMessage(text="Please select the face you wish to {actmsg} from the website in this link".format(actmsg=action_msg.lower()))]
            )
        )
        #Send user to LIFF website search image page
        ""
    elif len(cluster_list) > 0:
        #Push message to tell user to select a face
        line_bot_api.push_message(
            PushMessageRequest(
                to=userId,
                messages=[TextMessage(text="Please select the face you wish to {actmsg} from the following menus".format(actmsg=action_msg.lower()))]
            )
        )
        #Create carousel menus and send to user
        group_carousel_menus = create_carousel_menus_face(faceList=cluster_list, actType=action_type)
        if group_carousel_menus is False:
            raise Exception("While processing Post Event {actmsg}, the issue was occured at creating carousel menu for face".format(actmsg=action_msg))
        else:
            url_headers = {"Authorization":"Bearer {access_token}".format(access_token=BOT_ACCESS_TOKEN), "Content-Type":"application/json"}
            carousel_menu_post_data = {
                "to": userId,
                "messages": [group_carousel_menus]
            }
            post_menu_response = requests.post(url="https://api.line.me/v2/bot/message/push", headers=url_headers, json=carousel_menu_post_data)
            if post_menu_response.status_code != 200:
                raise Exception("There was an issue occured at sending carousel menu for selecting face", post_menu_response.status_code, post_menu_response.text)
    else:
        line_bot_api.push_message(
            PushMessageRequest(
                to=userId,
                messages=[TextMessage(text="Sorry, but we could not find any images that can be use in the moment.\nPlease try again later.")]
            )
        )


def res_sel_face(action_type: str, userId: str, groupId: str, clusterId: str) -> None:
    #Log user choose a face to search image by face on LineCMS official
    log_message = "User chose face from cluster id {clusterId} from carousel menu on LineCMS official".format(clusterId=clusterId)
    log_data = create_log_col_data("Official", userId, log_message, datetime.now())
    col_logs.insert_one(log_data)

    if action_type == "image":
        #Find images from cluster id and group id, then send image(s) to user
        for image in col_images.find({"group_id":groupId}):
            cluster_id_list = []
            for clusterObjId in image["cluster_ids"]:   ### Area that might have problem with ObjectId to string
                cluster_id_list.append(str(clusterObjId))
            if clusterId in cluster_id_list:
                image_url = TEMP_SERVER_URL+"/linecms/image/"+image["_id"]
                line_bot_api.push_message(
                    PushMessageRequest(
                        to=userId,
                        messages=[ImageMessage(originalContentUrl=image_url, previewImageUrl=image_url)]
                    )
                )
    elif action_type == "graph": #ASK Field for sending post to model api for making relationship graph
        #send group id,cluster id,user id and request timestamp to model server api to request relationship graph
        # isPostGraph, postGraphMsg = post_relationshipGraph(groupId, clusterId, userId)
        # if not isPostGraph:
        #     raise Exception("Fail to post relationship graph. {msg}".format(msg=postGraphMsg))
        
        #send message to user
        line_bot_api.push_message(
            PushMessageRequest(
                to=userId,
                messages=[TextMessage(text="We receive your request. We will send the result in here after we finish making relationship graph.\nPlease come back and check again later.")]
            )
        )
    else:
        raise Exception("Incorrect action type argument")
    

def post_relationshipGraph(groupId: str, clusterId: str, userId: str):
    model_api_data = {
        "group_id":groupId,
        "cluster_id":clusterId,
        "user_id":userId,
        #"request_time":datetime.now()
    }
    model_api_url = MODEL_SERVER_GRAPH_LINK
    max_retry = 3
    retry_count = 0
    while retry_count < max_retry:
        response = requests.post(model_api_url,json=model_api_data)
        if response.status_code == 200:
            return True, "Request sent successful"
        elif response.status_code == 500:
            time.sleep(1)
            retry_count += 1
        else:
            return False, "Post returned unexpected status.\nres_status_code={code}\nres_text={text}".format(code=response.status_code, text=response.text)
    else:
        return False, "Retry post model api reach maximum value"



#Create directories in docker environment (the current path is in ./app so add ".." to start at root path)
docker_saved_file_paths = [SAVE_IMAGE_PATH, SAVE_FACE_PATH, SAVE_GRAPH_PATH, SAVE_FILE_PATH, SAVE_GROUPPROFILE_PATH]
for saved_path in docker_saved_file_paths:
    os.makedirs(".."+saved_path, exist_ok=True)

# Connect to database
failDBCon_count = 0
dbMsg = ""
while failDBCon_count < 10:
    isConnect, dbMsg = set_db_variables(dbClient=linecms_database.getdbclient())
    if isConnect:
        break
    else:
        failDBCon_count += 1
else:
    raise Exception("Failed to connect to MongoDB. ErrorMessage:",dbMsg)
    # print("Failed to connect to MongoDB. ErrorMessage:",dbMsg)



@app.route("/")
def test():
    return "Testing Successful", 200

@app.route("/api/liff", methods=["POST"])
def resonse_liff():
    body_json = request.get_json()
    return "OK", 200

@app.route("/api/model", methods=["POST"])
def response_model():
    body_json = request.get_json()
    return "OK", 200

@app.route("/api/linewh", methods=["POST"])
def linewebhook():

    # get X-Line-Signature header value
    signature = request.headers["X-Line-Signature"]

    # get request body as text
    body = request.get_data(as_text=True)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return "OK"


@handler.add(event=MessageEvent, message=TextMessageContent)
def handle_textmessage(event):
    global api_client, line_bot_api
    # get data from webhook event
    event_data_dict = json.loads(event.to_json())
    #user_text = event.message.text
    user_id = event_data_dict["source"]["userId"]
    event_type = event_data_dict["source"]["type"]

    if event_type == "user":
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=event.reply_token,
                messages=[TextMessage(text="We see your text message in official account!")]
            )
        )


# save image to local server in public directory
@handler.add(event=MessageEvent, message=ImageMessageContent)
def save_imagemessage(event):
    message_id = event.message.id # get image message id -> can directly get
    # convert to python dict
    event_data_dict = json.loads(event.to_json())
    group_id = event_data_dict["source"]["groupId"] # get group id of source of image
    user_id = event_data_dict["source"]["userId"]
    event_timestamp = str(event_data_dict["timestamp"])
    
    #Create new image file name
    random_str = "".join(random.choices(string.ascii_letters + string.digits, k=10))
    image_filename = hashlib.sha1(bytes(random_str+event_timestamp,encoding="utf-8")).hexdigest()
    
    #Get image from Line API
    content_url = "https://api-data.line.me/v2/bot/message/{messageId}/content"
    url_headers = {"Authorization":"Bearer {access_token}".format(access_token=BOT_ACCESS_TOKEN)}
    image_data = requests.get(url=content_url.format(messageId = str(message_id)),headers=url_headers)
    
    #Save data to the server in public directory
    with open(file=SAVE_IMAGE_PATH+image_filename+".jpg", mode="wb") as imagefile:
        for chunk in image_data.iter_content():
            imagefile.write(chunk)
        imagefile.close()
    
    #Send new image data to database
    new_image_data = create_image_col_data(imageName=image_filename+".jpg", groupId=group_id, messageId=message_id, senderId=user_id)
    col_images.insert_one(new_image_data)

    #Log user send image to database
    log_message = "User id {userId} sent an image id {msgId} to group chat".format(userId=user_id, msgId=message_id)
    log_data = create_log_col_data("Group", group_id, log_message, datetime.now())
    col_logs.insert_one(log_data)

    #Update image_count in group data
    return_data = col_groups.find_one_and_update(filter={"_id":group_id}, update={"$inc":{"image_count":1}, "$set":{"last_used":datetime.now()}})
    #Raise error if database cannot find the group data match with group id
    if return_data is None:
        raise Exception("While updating image count, database cannot find the data from group id")

    #Sent request to model api to create face image from new image
    model_api_data = {
        "image_name":image_filename+".jpg",
        "group_id":group_id
    }
    model_api_url = MODEL_SERVER_IMAGE_LINK
    max_retry = 3
    retry_count = 0
    while retry_count < max_retry:
        response = requests.post(model_api_url,json=model_api_data)
        if response.status_code == 200:
            break
        elif response.status_code == 500:
            time.sleep(1)
            retry_count += 1
        else:
            print(response.status_code, response.text)
            break
    else:
        print("Retry post model api reach maximum value")

    #Log the process (both done and have errors) here
    ### insert log here ###

# Save file to local server
@handler.add(event=MessageEvent, message=FileMessageContent)
def handle_fileMessage(event):
    messageId = event.message.id # get file message id
    # convert to python dict and get required data
    eventDataDict = json.loads(event.to_json())
    groupId = eventDataDict["source"]["groupId"] # get group id of source of image
    userId = eventDataDict["source"]["userId"]
    eventTimestamp = str(eventDataDict["timestamp"])
    fileName = eventDataDict["message"]["fileName"]
    #fileSize = eventDataDict["message"]["fileSize"] # file size in bytes
    fileExt = str(fileName).split(".").pop() # file extension (testing)

    #Create local file name
    random_str = "".join(random.choices(string.ascii_letters + string.digits, k=10))
    localFileName = hashlib.sha1(bytes(random_str+eventTimestamp,encoding="utf-8")).hexdigest()

    #Get file from Line API
    content_url = "https://api-data.line.me/v2/bot/message/{messageId}/content"
    url_headers = {"Authorization":"Bearer {access_token}".format(access_token=BOT_ACCESS_TOKEN)}
    fileData = requests.get(url=content_url.format(messageId = str(messageId)),headers=url_headers)    

    #Save file to the server (with correct file extension)
    with open(file=SAVE_FILE_PATH+localFileName+"."+fileExt, mode="wb") as docfile:
        for chunk in fileData.iter_content():
            docfile.write(chunk)
        docfile.close()

    #Send new file data to database
    newFileData = create_file_col_data(localFileName+"."+fileExt, groupId, fileName, messageId, userId)
    col_files.insert_one(newFileData)

    #Log user send file to database
    log_message = "User id {userId} sent file id {msgId} to group chat".format(userId=userId, msgId=messageId)
    log_data = create_log_col_data("Group", groupId, log_message, datetime.now())
    col_logs.insert_one(log_data)

    #Update file_count in group data
    return_data = col_groups.find_one_and_update(filter={"_id":groupId}, update={"$inc":{"file_count":1}, "$set":{"last_used":datetime.now()}})
    #Raise error if database cannot find the group data match with group id
    if return_data is None:
        raise Exception("While updating image count, database cannot find the data from group id")

    



#Handle event when chat bot join group
@handler.add(event=JoinEvent)
def create_data_group(event):
    global api_client, line_bot_api
    # convert to python dict
    event_data_dict = json.loads(event.to_json())
    group_id = event_data_dict["source"]["groupId"]

    if col_groups.find_one({"_id":group_id}) is None:
        new_group_data = create_group_col_data(line_bot_api,group_id)
        col_groups.insert_one(new_group_data)
        #Log chat bot join new group chat
        log_message = "Chat bot has joined new group chat"
        log_data = create_log_col_data("Group", group_id, log_message, datetime.now())
        #col_logs.insert_one(log_data)
    else:
        #Change status to "Active" in case of chat bot left and joined group within 3 days
        join_group_data = col_groups.find_one(filter={"_id":group_id})
        if join_group_data["status"] == "Deleted":
            col_groups.find_one_and_update(filter={"_id":group_id}, update={"$set":{"status":"Active", "last_used":datetime.now()}})
        
        #Send current information in the system message to group chat
        line_bot_api.push_message(
            PushMessageRequest(
                to=group_id,
                messages=[TextMessage(text="Current information: saved image = {imgCount} images".format(imgCount=str(join_group_data["image_count"])))]
            )
        )

        #Log chat bot rejoin group chat within 3 days
        log_message = "Chat bot has rejoined group chat"
        log_data = create_log_col_data("Group", group_id, log_message, datetime.now())
        #col_logs.insert_one(log_data)
    col_logs.insert_one(log_data)

    #Send consent policy to group chat
    line_bot_api.push_message(
        PushMessageRequest(
            to=group_id,
            messages=[TextMessage(text="Consent")]
        )
    )
    #Send initial information and brief usage to group chat
    line_bot_api.push_message(
        PushMessageRequest(
            to=group_id,
            messages=[TextMessage(text="Initial information and brief usage LineCMS official")]
        )
    )


#Handle event when chat bot leave the group
@handler.add(event=LeaveEvent)
def handle_leavegroup(event):
    event_data_dict = json.loads(event.to_json())
    group_id = event_data_dict["source"]["groupId"]

    #Update status and last_used time of group on database
    if col_groups.find_one(filter={"_id":group_id}) is None:
        raise Exception("while processing chat bot leave group event, database cannot find group data from group id")
    else:
        col_groups.find_one_and_update(filter={"_id":group_id}, update={"$set":{"status":"Deleted", "last_used": datetime.now()}})
        #Log chat bot left group chat
        log_message = "Chat bot has left group chat"
        log_data = create_log_col_data("Group", group_id, log_message, datetime.now())
        col_logs.insert_one(log_data)


#Handle event when user join the group with chat bot in it
@handler.add(event=MemberJoinedEvent)
def handle_user_join_group(event):
    event_data_dict = json.loads(event.to_json())
    group_id = event_data_dict["source"]["groupId"]
    join_member_list = event_data_dict["joined"]["members"]
    join_member_id_list = []
    
    #Get all user ids from member list
    for member in join_member_list:
        join_member_id_list.append(member["userId"])
    
    #Update member ids of group data on database with new id(s)
    if col_groups.find_one(filter={"_id":group_id}) is None:
        raise Exception("while processing member joined event, database cannot find group data from group id")
    else:
        group_data = col_groups.find_one(filter={"_id":group_id})
        group_member_ids = group_data["member_ids"]
        group_member_ids.extend(join_member_id_list)
        col_groups.find_one_and_update(filter={"_id":group_id}, update={"$set":{"member_ids":group_member_ids}})
        #Log user(s) joined group chat
        if len(join_member_id_list) > 1:
            uidStr = ""
            for uid in join_member_id_list:
                uidStr = uidStr + uid
                if uid != join_member_id_list[-1]:
                    uidStr = uidStr + ", "
            log_message = "There are {userCount} users joined group chat. User ids = [{idStr}]".format(userCount=len(join_member_id_list), idStr=uidStr)
        else:
            log_message = "There is {userCount} user joined group chat. User id = {uid}".format(userCount=len(join_member_id_list), uid=join_member_id_list[0])
        log_data = create_log_col_data("Group", group_id, log_message, datetime.now())
        col_logs.insert_one(log_data)

#Handle event when user leave the group with chat bot in it
@handler.add(event=MemberLeftEvent)
def handle_user_leave_group(event):
    event_data_dict = json.loads(event.to_json())
    group_id = event_data_dict["source"]["groupId"]
    left_member_list = event_data_dict["left"]["members"]
    left_member_id_list = []

    #Get all user ids from member list
    for member in left_member_list:
        left_member_id_list.append(member["userId"])
    
    if col_groups.find_one(filter={"_id":group_id}) is None:
        raise Exception("while processing member left event, database cannot find group data from group id")
    else:
        group_data = col_groups.find_one(filter={"_id":group_id})
        group_member_ids = group_data["member_ids"]

        #Remove left user id from member ids
        for userId in left_member_id_list:
            group_member_ids.remove(userId)
        
        #Update group data on database
        col_groups.find_one_and_update(filter={"_id":group_id}, update={"$set":{"member_ids":group_member_ids}})

        #Log user(s) left group chat
        if len(left_member_id_list) > 1:
            uidStr = ""
            for uid in left_member_id_list:
                uidStr = uidStr + uid
                if uid != left_member_id_list[-1]:
                    uidStr = uidStr + ", "
            log_message = "There are {userCount} users left group chat. User ids = [{idStr}]".format(userCount=len(left_member_id_list), idStr=uidStr)
        else:
            log_message = "There is {userCount} user left group chat. User id = {uid}".format(userCount=len(left_member_id_list), uid=left_member_id_list[0])
        log_data = create_log_col_data("Group", group_id, log_message, datetime.now())
        col_logs.insert_one(log_data)
    

#Handle event when user added or unblocked LineCMS official account
@handler.add(event=FollowEvent)
def handle_follow_unblock_official(event):
    global api_client, line_bot_api

    event_data_dict = json.loads(event.to_json())
    user_id = event_data_dict["source"]["userId"]
    #Create new user data in dictionary format when user add official as a friend for the first time
    if col_users.find_one(filter={"_id":user_id}) is None:
        new_user_data = {
            "_id": user_id,
            "status": "Active",
            "added_time": datetime.now(),
            "last_used": datetime.now()
        }
        col_users.insert_one(new_user_data)

        #Send greeting message to user
        line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text="Greeting Text")]
            )
        )

        #Log new user add official as a friend
        log_message = "New user added LineCMS official as a friend"
        log_data = create_log_col_data("Official", user_id, log_message, datetime.now())
        # col_logs.insert_one(log_data)
    else:
        col_users.find_one_and_update(filter={"_id":user_id}, update={"$set":{"status":"Active", "last_used":datetime.now()}})

        #Send welcome back message to user
        line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text="Welcome back!")]
            )
        )
        #Log user unblock official
        log_message = "User unblocked LineCMS official"
        log_data = create_log_col_data("Official", user_id, log_message, datetime.now())
        # col_logs.insert_one(log_data)
    col_logs.insert_one(log_data)
    

#Handle event when user blocked LineCMS official account
@handler.add(event=UnfollowEvent)
def handle_unfollow_official(event):
    event_data_dict = json.loads(event.to_json())
    user_id = event_data_dict["source"]["userId"]
    return_data = col_users.find_one_and_update(filter={"_id":user_id}, update={"$set":{"status":"Blocked"}})

    #Raise error if database cannot find the group data match with group id
    if return_data is None:
        raise Exception("While processing unfollow event, database cannot find the data from user id")
    
    #Log user block official
    log_message = "User blocked LineCMS official"
    log_data = create_log_col_data("Official", user_id, log_message, datetime.now())
    col_logs.insert_one(log_data)


#Handle event when user unsend images (,files) in the group with chat bot in it
@handler.add(event=UnsendEvent)
def handle_unsend_message(event):
    event_data_dict = json.loads(event.to_json())
    message_id = event_data_dict["unsend"]["messageId"]
    source_type = event_data_dict["source"]["type"]
    group_id = event_data_dict["source"]["groupId"]
    user_id = event_data_dict["source"]["userId"]

    #Delete image (and face) data on database if user unsend from group
    if source_type == "group":
        #Find image data on database (have to change code if we store files as well)
        if col_images.find_one(filter={"group_id":group_id, "message_id":message_id}) is None:
            raise Exception("While processing unsend image, database cannot find the image data from group id and message id")
        else:
            #Delete image data on database and image file
            unsend_image = col_images.find_one_and_delete(filter={"group_id":group_id, "message_id":message_id})
            image_name = unsend_image["_id"]
            os.remove(path=SAVE_IMAGE_PATH+image_name)

            #Delete face data on database and face file if created from original image
            if col_faces.find_one(filter={"image_link":image_name}) is not None:
                unsend_face = col_faces.find_one_and_delete(filter={"image_link":image_name})
                face_name = unsend_face["_id"]
                os.remove(path=SAVE_FACE_PATH+face_name)
            
            #Update image_count in group data
            col_groups.find_one_and_update(filter={"_id":group_id}, update={"$inc":{"image_count":-1}})

            #Log user unsend image or file in group chat
            log_message = "User id {userId} has unsended file/image id {msgId} in group chat".format(userId=user_id, msgId=message_id)
            log_data = create_log_col_data("Group", group_id, log_message, datetime.now())
            col_logs.insert_one(log_data)

            #Sent delete command to model api when user unsend image
            model_api_data = {
                "image_name":image_name,
                "group_id":group_id,
                "command": "delete"
            }
            model_api_url = MODEL_SERVER_OTHER_LINK
            max_retry = 3
            retry_count = 0
            while retry_count < max_retry:
                response = requests.post(model_api_url,json=model_api_data)
                if response.status_code == 200:
                    break
                elif response.status_code == 500:
                    time.sleep(1)
                    retry_count += 1
                else:
                    print(response.status_code, response.text)
                    break
            else:
                print("Retry post model api reach maximum value")

#Handle event when user tap menu from rich menu in LineCMS official
@handler.add(event=PostbackEvent)
def handle_postback_event(event):
    global api_client, line_bot_api
    event_data_dict = json.loads(event.to_json())
    user_id = event_data_dict["source"]["userId"]
    postback_data = event_data_dict["postback"]["data"]

    if postback_data == "action=searchImage":
        action_img_graph(action="searchImage", userId=user_id)
    elif postback_data == "action=CreateRelaGraph": #Optional for user tap 'create relationship graph' menu on rich menus
        action_img_graph(action="createRelaGraph", userId=user_id)
    elif "selectGroup=1" in postback_data:
        #Get group id from postback data
        data_list = postback_data.split(sep="&")
        act_type = data_list.pop().replace("type=","")
        group_id = data_list.pop().replace("groupId=","")

        res_sel_group(action_type=act_type, userId=user_id, groupId=group_id)
    elif "selectFace=1" in postback_data:
        #Get cluster id and group id from postback data
        data_list = postback_data.split(sep="&")
        act_type = data_list.pop().replace("type=","")
        group_id = data_list.pop().replace("groupId=","")
        cluster_id_str = data_list.pop().replace("clusterId=","")

        res_sel_face(action_type=act_type, userId=user_id, groupId=group_id, clusterId=cluster_id_str)
    else:
        line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text="This feature is unavailable at the moment")]
            )
        )



    

    
    

    