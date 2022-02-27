import asyncio
import websockets
import contextvars
import base64
import aiohttp
import os
import re
import json

# VARIABLE DEFINITIONS

rooms = [] # list of all rooms
lastRoomID = 0 # id of the last created room. Gets incremented by 1 for every new room
roomLock = asyncio.Lock() # lock that ensures no concurrent access to the rooms[] array. (Not sure where/if entirely necessary with asyncio but better safe than sorry.)

socket = contextvars.ContextVar("socket") # the user socket of the current context
userID = contextvars.ContextVar("userID", default = None) # the userID of the user in the current context (if authenticated)
verified = contextvars.ContextVar("verified") # the userID of the user in the current context (if authenticated)
currentRoom = contextvars.ContextVar("currentRoom", default = None) # the room that the user in the current context is in

iconAmount = 19
iconNames = [
	"???",
	"logix",
	"dev",
	"chat",
	"help",
	"cool",
	"epic",
	"bored",
	"anime",
	"furry",
	"ncr",
	"sugoi",
	"kawaii",
	"japanese",
	"korean",
	"chinese",
	"german",
	"russian",
	"french"
]

richMessageCodes = [
	# emoji
	(":alien:", "<sprite name=alien>"),
	(":anger:", "<sprite name=anger>"),
	(":angry:", "<sprite name=anger>"),
	(":mad:", "<sprite name=anger>"),
	(":grumpy:", "<sprite name=anger>"),
	(":pissed:", "<sprite name=anger>"),
	(":cool:", "<sprite name=cool>"),
	(":sunglasses:", "<sprite name=cool>"),
	(":shades:", "<sprite name=cool>"),
	(":fancy:", "<sprite name=fancy>"),
	(":sir:", "<sprite name=fancy>"),
	(":monocle:", "<sprite name=fancy>"),
	(":frown:", "<sprite name=frown>"),
	(":sad:", "<sprite name=frown>"),
	(":hm:", "<sprite name=confused>"),
	(":confused:", "<sprite name=confused>"),
	(":?:", "<sprite name=confused>"),
	(":ill:", "<sprite name=ill>"),
	(":sick:", "<sprite name=ill>"),
	(":puke:", "<sprite name=ill>"),
	(":happy:", "<sprite name=happy>"),
	(":ninja:", "<sprite name=ninja>"),
	(":o:", "<sprite name=open_mouth>"),
	(":open:", "<sprite name=open_mouth>"),
	(":shock:", "<sprite name=shock>"),
	(":smile:", "<sprite name=smile>"),
	(":laugh:", "<sprite name=laugh>"),
	(":upsidedown:", "<sprite name=upside_down>"),
	(":flip:", "<sprite name=upside_down>"),
	(":flipped:", "<sprite name=upside_down>"),
	(":vr:", "<sprite name=vr>"),
	(":VR:", "<sprite name=vr>"), # all this should probably be case-insensitive but that can be a thing for later.
	(":xd:", "<sprite name=grin>"),
	(":XD:", "<sprite name=grin>"),
	(":grin:", "<sprite name=grin>"),
	(":ghost:", "<sprite name=ghost>"),
	(":boo:", "<sprite name=ghost>"),
	(":anime:", "<sprite name=anime>"),
	(":highfive:", "<sprite name=high_five>"),
	(":gunleft:", "<sprite name=gun_left>"),
	(":gunl:", "<sprite name=gun_left>"),
	(":gun:", "<sprite name=gun_right>"),
	(":gunright:", "<sprite name=gun_right>"),
	(":gunr:", "<sprite name=gun_right>"),
	(":arm:", "<sprite name=arm>"),
	(":loric:", "<sprite name=loric>"),
	(":cheers:", "<sprite name=cheers>"),
	(":awesome:", "<sprite name=awesome>"),
	(":epic:", "<sprite name=awesome>"),
	(":sleep:", "<sprite name=sleep>"),
	(":sleeping:", "<sprite name=sleep>"),
	(":raise:", "<sprite name=raised_eyebrow>"),
	(":brow:", "<sprite name=raised_eyebrow>"),
	(":money:", "<sprite name=money_eyes>"),
	(":cash:", "<sprite name=money_eyes>"),
	(":$:", "<sprite name=money_eyes>"),
	(":smirk:", "<sprite name=smirk>"),
	# kaomoji
	(";shrug;", "¯\_(ツ)_/¯"),
	(";flip;", "(╯°□°)╯︵ ┻━┻"),
	(";unflip;", "┬─┬ノ( º _ ºノ)"),
	# RTF tags
	("[b]", "<b>"),
	("[/b]", "</b>"),
	("[i]", "<i>"),
	("[/i]", "</i>"),
	("[u]", "<u>"),
	("[/u]", "</u>"),
	("[s]", "<s>"),
	("[/s]", "</s>"),
	("[sub]", "<sub>"),
	("[/sub]", "</sub>"),
	("[sup]", "<sup>"),
	("[/sup]", "</sup>"),
	("[br]", "<br>"),
	("[big]", "<size=480>"),
	("[/big]", "</size>")
]

# SLASH COMMANDS (all of these are called with the room lock already engaged and with currentRoom existing)
# All of them return a boolean for whether or not the command was successful.

globalAdmins = ["U-Psychpsyo"]
alwaysAdmins = ["U-Psychpsyo"]

async def clearBadWords(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get() or not verified.get():
		await socket.get().send("err:You must be the verified owner of this room to use this command.")
		return False
	
	currentRoom.get()["badWords"] = []
	# save default (always open) rooms to file if necessary
	if currentRoom.get()["alwaysOpen"]:
		saveDefaultRooms()
	return True

async def addBadWord(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get() or not verified.get():
		await socket.get().send("err:You must be the verified owner of this room to use this command.")
		return False
	
	currentRoom.get()["badWords"].append(params)
	# save default (always open) rooms to file if necessary
	if currentRoom.get()["alwaysOpen"]:
		saveDefaultRooms()
	return True

async def removeBadWord(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get() or not verified.get():
		await socket.get().send("err:You must be the verified owner of this room to use this command.")
		return False
	
	try:
		currentRoom.get()["badWords"].remove(params)
		# save default (always open) rooms to file if necessary
		if currentRoom.get()["alwaysOpen"]:
			saveDefaultRooms()
		return True
	except ValueError:
		await socket.get().send("err:The word you were trying to remove was not on the list of bad words.")
		return False

async def setRoomName(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get() or not verified.get():
		await socket.get().send("err:You must be the verified owner of this room to use this command.")
		return False
	
	# set room name and inform all users in the room
	currentRoom.get()["name"] = params
	for user in currentRoom.get()["users"]:
		await user.send("nme:" + "<noparse=" + str(len(params)) + ">" + params)
	# save default (always open) rooms to file if necessary
	if currentRoom.get()["alwaysOpen"]:
		saveDefaultRooms()
	return True

async def setRoomIcon(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get() or not verified.get():
		await socket.get().send("err:You must be the verified owner of this room to use this command.")
		return False
	
	newIcon = -1
	# check if the paramter was the name of a room icon
	try:
		newIcon = iconNames.index(params.lower())
	except:
		pass
	# if it wasn't, check if it was the index.
	if newIcon < 0:
		try:
			newIcon = int(params)
		except:
			pass
	
	# validate the parsed index
	if newIcon < 0 or newIcon >= iconAmount:
		await socket.get().send("err:You specified an invalid room icon.")
		return False
	
	currentRoom.get()["icon"] = newIcon
	# save default (always open) rooms to file if necessary
	if currentRoom.get()["alwaysOpen"]:
		saveDefaultRooms()
	return True

# makes it so that the room does not disappear when everyone leaves it.
async def makePersistent(params):
	# check if the user is a global admin
	if userID.get() not in globalAdmins or not verified.get():
		await socket.get().send("err:You must be a verified admin to use this command.")
		return False
	
	currentRoom.get()["alwaysOpen"] = True
	saveDefaultRooms()
	return True

# makes it so that the room disappears when everyone leaves it.
async def makeNonpersistent(params):
	# check if the user is a global admin or owner of the room and verified
	if (userID.get() not in globalAdmins and currentRoom.get()["owner"] != userID.get()) or not verified.get():
		await socket.get().send("err:You must be a verified admin or owner of this room to use this command.")
		return False
	
	currentRoom.get()["alwaysOpen"] = False
	return True

# remove all messages from the current room.
async def clearMessageHistory(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get() or not verified.get():
		await socket.get().send("err:You must be the verified owner of this room to use this command.")
		return False
	
	currentRoom.get()["messages"] = []
	# inform all users in the room
	for user in currentRoom.get()["users"]:
		await user.send("clr")
	return True

# give someone admin permissions.
async def grantAdminPerms(params):
	# check if the user is a global admin
	if userID.get() not in globalAdmins or not verified.get():
		await socket.get().send("err:You must be a verified admin to use this command.")
		return False
	
	if not params.startswith("U-") or " " in params or params == "": # this is only a very crude, incorrect way to verify a user ID but it should at least avoid some typos.
		await socket.get().send("err:You must supply makeadmin with a valid user ID.")
		return False
	
	try:
		globalAdmins.remove(params)
		return True
	except ValueError:
		await socket.get().send("err:" + params + " is not an admin.")
		return False

# revoke someone's admin permissions.
async def removeAdminPerms(params):
	# check if the user is a global admin
	if userID.get() not in globalAdmins or not verified.get():
		await socket.get().send("err:You must be a verified admin to use this command.")
		return False
	
	if not params.startswith("U-") or " " in params: # this is only a very crude, incorrect way to verify a user ID but it should at least avoid some typos.
		await socket.get().send("err:You must supply makeadmin with a valid user ID.")
		return False
	
	# is the user in alwaysAdmins? (undemoteable)
	if params in alwaysAdmins:
		await socket.get().send("err:You cannot take admin perms from " + params + ".")
		return False
	
	globalAdmins.remove(params)
	return True

# sends a video in the current room.
async def sendVideo(params):
	if len(params) == 0:
		await socket.get().send("err:You must supply a video link.")
		return False
	
	message = "vid:" + userID.get() + "|" + str(verified.get()) + "|" + params
	
	currentRoom.get()["messages"].append(message)
	currentRoom.get()["messages"] = currentRoom.get()["messages"][-currentRoom.get()["messageLimit"]:]
	for user in currentRoom.get()["users"]:
		await user.send(message)
	return True

# sets the limit for how many of the messages in the current room are kept around.
async def setMessageLimit(params):
	# check if the user is a global admin or owner of the room and verified
	if (userID.get() not in globalAdmins and currentRoom.get()["owner"] != userID.get()) or not verified.get():
		await socket.get().send("err:You must be a verified admin or owner of this room to use this command.")
		return False
	
	try:
		params = int(params)
	except:
		await socket.get().send("err:You must supply the command with a number.")
		return False
	
	if params < 0:
		await socket.get().send("err:Number of messages retained cannot be negative.")
		return False
	
	# check if the user is a global admin when setting to a high value.
	if params > 100 and (userID.get() not in globalAdmins or not verified.get()):
		await socket.get().send("err:You must be a verified admin to set the message limit to more than 100.")
		return False
	
	currentRoom.get()["messageLimit"] = params
	# save default (always open) rooms to file if necessary
	if currentRoom.get()["alwaysOpen"]:
		saveDefaultRooms()
	return True

# transfer ownership of the current room to someone else.
async def transferOwnership(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get() or not verified.get():
		await socket.get().send("err:You must be the verified owner of this room to use this command.")
		return False
	
	if not params.startswith("U-") or " " in params or params == "": # this is only a very crude, incorrect way to verify a user ID but it should at least avoid some typos.
		await socket.get().send("err:You must supply tranferownership with a valid user ID.")
		return False
	
	currentRoom.get()["owner"] = params
	# save default (always open) rooms to file if necessary
	if currentRoom.get()["alwaysOpen"]:
		saveDefaultRooms()
	return True

# sets the current room to read only, so no new messages can be sent in it (except by the owner)
async def makeReadOnly(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get() or not verified.get():
		await socket.get().send("err:You must be the verified owner of this room to use this command.")
		return False
	
	currentRoom.get()["readOnly"] = True
	# save default (always open) rooms to file if necessary
	if currentRoom.get()["alwaysOpen"]:
		saveDefaultRooms()
	return True

# disables readonly in the current room so people can send messages again
async def unmakeReadOnly(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get() or not verified.get():
		await socket.get().send("err:You must be the verified owner of this room to use this command.")
		return False
	
	currentRoom.get()["readOnly"] = False
	# save default (always open) rooms to file if necessary
	if currentRoom.get()["alwaysOpen"]:
		saveDefaultRooms()
	return True

slashCommands = {
	"clearbadwords": clearBadWords,
	"addbadword": addBadWord,
	"removebadword": removeBadWord,
	"setroomname": setRoomName,
	"setroomicon": setRoomIcon,
	"makepersistent": makePersistent,
	"makenonpersistent": makeNonpersistent,
	"clearmessagehistory": clearMessageHistory,
	"makeadmin": grantAdminPerms,
	"takeadmin": removeAdminPerms,
	"video": sendVideo,
	"setmessagelimit": setMessageLimit,
	"transferownership": transferOwnership,
	"makereadonly": makeReadOnly,
	"unmakereadonly": unmakeReadOnly
}

# FUNCTIONS THAT PERTAIN TO CORE ROOM MANAGEMENT / MESSAGE SENDING

# returns room on sucess or an error string on error.
async def createNewRoom(name, icon, userID, bySystem = False, messageLimit = 100, readOnly = False, badWords = []):
	global lastRoomID
	global iconAmount
	global rooms
	async with roomLock:
		# validate room
		if len(rooms) >= 100:
			return "Room cap reached, cannot create more rooms."
		if len(name) == 0:
			name = "Unnamed Room #" + str(lastRoomID)
		# validate userID if the room isn't created by the system
		if not bySystem and not verified.get():
			return "Unverified users cannot create rooms.\nYou need to connect from your dash to verify your identity to create a room."
		
		# truncate room name to 50 characters.
		if len(name) > 50:
			name = name[:50]
		
		# turn invalid icons into icon 0 (???)
		if icon < 0 or icon >= iconAmount:
			icon = 0
		
		# create the room
		lastRoomID += 1
		rooms.append({
			"id": lastRoomID,
			"name": name,
			"users": [] if bySystem else [socket.get()],
			"owner": userID,
			"messages": [],
			"icon": icon,
			"alwaysOpen": True if bySystem else False,
			"badWords": badWords,
			"messageLimit": messageLimit,
			"readOnly": readOnly
		})
		
		# add user to the room
		if not bySystem:
			currentRoom.set(rooms[-1])
			await socket.get().send("jnd:" + "<noparse=" + str(len(rooms[-1]["name"])) + ">" + rooms[-1]["name"])

def formatRichMessage(message, badWords):
	newMessage = [message]
	for code in richMessageCodes:
		message = newMessage
		newMessage = []
		for part in message:
			splitPart = part.split(code[0])
			originalInsertPos = len(splitPart) - 1
			for x in range(len(splitPart) - 1):
				splitPart.insert(originalInsertPos - x, code[0])
			newMessage += splitPart
	
	# at this point newMessage is the fully split message, so we can clear message and start parsing newMessage into it.
	message = ""
	
	currentChain = "" # the current chain of non-emoji text that needs to be escaped
	for part in newMessage:
		currentCode = next((code for code in richMessageCodes if code[0] == part), None)
		if currentCode:
			# we have reached an RTF tag, replace bad words with stars and write to message
			for word in badWords:
				currentChain = re.sub(re.escape(word), "*" * len(word), currentChain, flags=re.IGNORECASE)
			
			# insert the noparse and append to message
			message += "<noparse=" + str(len(currentChain)) + ">" + currentChain + currentCode[1]
			currentChain = ""
		else:
			currentChain += part
	
	# we may have some currentChain left over
	if currentChain != "":
		# also censor bad words here!
		for word in badWords:
			currentChain = re.sub(re.escape(word), "*" * len(word), currentChain, flags=re.IGNORECASE)
		
		message += "<noparse=" + str(len(currentChain)) + ">" + currentChain
	
	# return the fully substituted and replaced string
	return message

# gets called with roomLock already aquired.
async def sendMessage(message):
	# do not send messages if you have no userID
	if not userID.get():
		await socket.get().send("err:Client did not provide user ID. You won't be able to send messages.")
		return
	
	# trim whitespace off message
	message = message.strip()
	# do not send empty messages
	if len(message) == 0:
		return
	
	# trim messages down to 2000 characters
	message = message[:2000]
	
	# check if message is a video link and, if so, send a "vid:" reply instead of "msg:"
	isVideo = False
	if False: # for now this is done via the /video command
		isVideo = True
	else:
		# parse emoji and RTF tags into the message (this step also escapes all other RTF sequences.)
		badWords = []
		badWords = currentRoom.get()["badWords"]
		
		message = formatRichMessage(message, badWords)
	
	# prepare final message string
	message = ("vid:" if isVideo else "msg:") + userID.get() + "|" + str(verified.get()) + "|" + message
	
	currentRoom.get()["messages"].append(message)
	currentRoom.get()["messages"] = currentRoom.get()["messages"][-currentRoom.get()["messageLimit"]:]
	
	for user in currentRoom.get()["users"]:
		await user.send(message)

async def refreshRoomList():
	global rooms
	async with roomLock:
		for room in rooms:
			await socket.get().send("rom:" + str(room["id"]) + "|" + room["owner"] + "|" + str(len(room["users"])) + "|" + str(room["icon"]) + "|" + "<noparse=" + str(len(room["name"])) + ">" + room["name"])

# gets called with roomLock already aquired.
def saveDefaultRooms():
	roomsObject = {"rooms": []}
	for room in rooms:
		if room["alwaysOpen"]:
			roomsObject["rooms"].append({
				"name": room["name"],
				"icon": room["icon"],
				"owner": room["owner"],
				"messageLimit": room["messageLimit"],
				"readOnly": room["readOnly"],
				"badWords": room["badWords"]
			})
	
	with open("rooms.json", "w", encoding = "utf-8") as file:
		json.dump(roomsObject, file, ensure_ascii = False, indent = 4)

# websocket function
async def takeClient(websocket, path):
	global rooms
	print("Client connected.")
	socket.set(websocket)
	verified.set(False)
	await websocket.send("lft")
	await refreshRoomList()
	
	# ask client to verify themselves with a new verification key
	verificationCode = base64.b64encode(os.urandom(32)).decode("utf-8")
	await websocket.send("vrf:" + verificationCode)
	try:
		async for message in websocket:
			if message.startswith("[message]"): # sending a message
				# cut out the initial [message]
				message = message[9:]
				async with roomLock:
					if currentRoom.get():
						# check if the room is readOnly
						if currentRoom.get()["readOnly"] and (currentRoom.get()["owner"] != userID.get() or not verified.get()):
							await socket.get().send("err:This room is read-only. You must be the verified owner of this room to send messages here.")
							continue
						
						if message.startswith("/"):
							# slash commands
							command = message[1:message.find(" ") if message.find(" ") != -1 else len(message)].lower()
							# check if command exists
							if command not in slashCommands:
								# send red message and an error back
								await websocket.send("err:The entered command does not exist.")
								await websocket.send("msg:" + userID.get() + "|" + str(verified.get()) + "|<color=#fbb><noparse=" + str(len(message)) + ">" + message)
								continue
							params = message[message.find(" ") + 1:] if message.find(" ") > 0 else ""
							messageColor = "bfb" if await slashCommands[command](params) else "fbb"
							# send colored command message back
							await websocket.send("msg:" + userID.get() + "|" + str(verified.get()) + "|<color=#" + messageColor + "><noparse=" + str(len(message)) + ">" + message)
						else:
							await sendMessage(message)
			elif message.startswith("[join]"): # joining a room
				# if user is already in a room, ignore this message
				if currentRoom.get():
					await websocket.send("err:Cannot join a room when already in a room.")
					continue
				roomID = int(message[6:])
				async with roomLock:
					room = next((room for room in rooms if room["id"] == roomID), None)
					if room:
						currentRoom.set(room)
						room["users"].append(websocket)
						await websocket.send("jnd:" + "<noparse=" + str(len(room["name"])) + ">" + room["name"])
						# send all old messages of the room to the new user
						for message in room["messages"]:
							await websocket.send(message)
					else:
						await websocket.send("err:The room you tried to join does not exist anymore.")
			elif message.startswith("[leave]"): # leaving a room
				async with roomLock:
					if currentRoom.get():
						currentRoom.get()["users"].remove(websocket)
						if len(currentRoom.get()["users"]) == 0 and not currentRoom.get()["alwaysOpen"]:
							rooms.remove(currentRoom.get())
						currentRoom.set(None)
				# after removing them from the room, inform the client.
				await websocket.send("lft")
				await refreshRoomList()
			elif message.startswith("[room]"): # creating a room
				roomParams = message[6:].split("|") # [0] is the name, [1] is the icon.
				error = await createNewRoom(roomParams[0], int(roomParams[1]), userID.get())
				if error: # if a string got returned, it is an error
					await websocket.send("err:" + error)
			elif message.startswith("[refresh]"): # client wants to refresh their room list
				await refreshRoomList()
			elif message.startswith("[iam]"): # client identifies themselves (this DOES NOT verify them)
				userID.set(message[5:])
			elif message.startswith("[verify]"): # client claims to have verified themselves
				async with aiohttp.ClientSession() as session:
					# ask Neos API for their cloud var
					async with session.post("https://api.neos.com/api/readvars", json = [{"ownerId": userID.get(), "path": "U-Psychpsyo.verificationCode"}]) as response:
						jsonData = await response.json()
						# if they set it to the verificationCode, set them to verified.
						if jsonData[0].get("variable", {}).get("value", None) == verificationCode:
							verified.set(True)
	except:
		pass
	
	# user disconnected so it's time to clean up after them.
	async with roomLock:
		if currentRoom.get():
			currentRoom.get()["users"].remove(websocket)
			if len(currentRoom.get()["users"]) == 0 and not currentRoom.get()["alwaysOpen"]:
				rooms.remove(currentRoom.get())

loop = asyncio.get_event_loop()

# create the always-open default rooms
print("Creating default rooms.")
with open("rooms.json") as jsonFile:
	jsonData = json.load(jsonFile)
	for room in jsonData["rooms"]:
		loop.run_until_complete(createNewRoom(room["name"], room["icon"], room["owner"], bySystem = True, messageLimit = room.get("messageLimit", 100), readOnly = room["readOnly"], badWords = room.get("badWords", [])))

# start websocket and listen
print("Starting websocket.")
start_server = websockets.serve(takeClient, "localhost", 32759)

loop.run_until_complete(start_server)
loop.run_forever()