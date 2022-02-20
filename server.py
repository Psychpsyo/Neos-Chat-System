import asyncio
import websockets
import contextvars
import base64
import aiohttp
import os

# VARIABLE DEFINITIONS

rooms = [] # list of all rooms
lastRoomID = 0 # id of the last created room. Gets incremented by 1 for every new room
roomLock = asyncio.Lock() # lock that ensures no concurrent access to the rooms[] array. (Not sure where/if entirely necessary with asyncio but better safe than sorry.)

socket = contextvars.ContextVar("socket") # the user socket of the current context
userID = contextvars.ContextVar("userID", default = None) # the userID of the user in the current context (if authenticated)
verified = contextvars.ContextVar("verified") # the userID of the user in the current context (if authenticated)
currentRoom = contextvars.ContextVar("currentRoom", default = None) # the room that the user in the current context is in

iconAmount = 18

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
	("[big]", "<size=48>"),
	("[/big]", "</size>")
]

# SLASH COMMANDS (all of these are called with the room lock already engaged and with currentRoom existing)
# All of them return a boolean for whether or not the command was successful.

async def clearBadWords(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get():
		await socket.get().send("err:You must be the owner of this room to use this command.")
		return False
	
	currentRoom.get()["badWords"] = []
	return True

async def addBadWord(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get():
		await socket.get().send("err:You must be the owner of this room to use this command.")
		return False
	
	currentRoom.get()["badWords"].append(params)
	return True

async def removeBadWord(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get():
		await socket.get().send("err:You must be the owner of this room to use this command.")
		return False
	
	try:
		currentRoom.get()["badWords"].remove(params)
		return True
	except ValueError:
		await socket.get().send("err:The word you were trying to remove was not on the list of bad words.")
		return False

async def setRoomName(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get():
		await socket.get().send("err:You must be the owner of this room to use this command.")
		return False
	
	currentRoom.get()["name"] = params
	# TODO: message all users that their room name changed.
	return True

async def setRoomIcon(params):
	# check if the user is the owner of the room
	if currentRoom.get()["owner"] != userID.get():
		await socket.get().send("err:You must be the owner of this room to use this command.")
		return False
	
	currentRoom.get()["name"] = params
	# TODO: message all users that their room name changed.
	return True

slashCommands = {
	"clearbadwords": clearBadWords,
	"addbadword": addBadWord,
	"removebadword": removeBadWord,
	"setroomname": setRoomName
}

# FUNCTIONS THAT PERTAIN TO CORE ROOM MANAGEMENT / MESSAGE SENDING

# returns room on sucess or an error string on error.
async def createNewRoom(name, icon, userID, bySystem = False):
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
		if not bySystem:
			if not verified.get():
				return "Unverified users cannot create rooms.\nYou need to connect from your dash to verify your identity to create a room."
		
		# truncate room name to 50 characters.
		if len(name) > 50:
			name = name[:50]
		
		# turn invalid icons into icon 0 (???)
		if icon < 0 or icon >= iconAmount:
			icon = 0
		
		# create the room
		lastRoomID += 1
		rooms.append({"id": lastRoomID, "name": "<noparse=" + str(len(name)) + ">" + name, "users": [] if bySystem else [socket.get()] , "owner": userID, "messages": [], "icon": icon, "alwaysOpen": True if bySystem else False, "badWords": []})
		
		# add user to the room
		if not bySystem:
			currentRoom.set(rooms[-1])
			await socket.get().send("jnd:" + rooms[-1]["name"])

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
				currentChain.replace(word, "*" * len(word))
			
			# insert the noparse and append to message
			message += "<noparse=" + str(len(currentChain)) + ">" + currentChain + currentCode[1]
			currentChain = ""
		else:
			currentChain += part
	
	# we may have some currentChain left over
	if currentChain != "":
		message += "<noparse=" + str(len(currentChain)) + ">" + currentChain
	
	# return the fully substituted and replaced string
	return message

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
	
	# parse emoji and RTF tags into the message (this step also escapes all other RTF sequences.)
	badWords = []
	async with roomLock:
		badWords = currentRoom.get()["badWords"]
	
	message = formatRichMessage(message, badWords)
	
	# trim messages down to 2000 characters
	message = message[:2000]
	# TODO: Sanitize message more
	
	# prepare final message string
	message = "msg:" + userID.get() + "|" + str(verified.get()) + "|" + message
	
	currentRoom.get()["messages"].append(message)
	currentRoom.get()["messages"] = currentRoom.get()["messages"][-100:]
	
	async with roomLock:
		for user in currentRoom.get()["users"]:
			await user.send(message)

async def refreshRoomList():
	global rooms
	async with roomLock:
		for room in rooms:
			await socket.get().send("rom:" + str(room["id"]) + "|" + room["owner"] + "|" + str(len(room["users"])) + "|" + str(room["icon"]) + "|" + room["name"])


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
	#try:
	async for message in websocket:
		if message.startswith("[message]"): # sending a message
			# cut out the initial [message]
			message = message[9:]
			if currentRoom.get():
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
					async with roomLock:
						if currentRoom.get():
							messageColor = "bfb" if await slashCommands[command](params) else "fbb"
							# send green message back
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
					await websocket.send("jnd:" + room["name"])
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
	#except:
	#	pass
	
	# user disconnected so it's time to clean up after them.
	async with roomLock:
		if currentRoom.get():
			currentRoom.get()["users"].remove(websocket)
			if len(currentRoom.get()["users"]) == 0:
				rooms.remove(currentRoom.get())

loop = asyncio.get_event_loop()

# create the always-open default rooms
print("Creating default rooms.")
loop.run_until_complete(createNewRoom("Logix Help #1", 1, "U-Psychpsyo", bySystem = True))
loop.run_until_complete(createNewRoom("Logix Help #2", 1, "U-Psychpsyo", bySystem = True))
loop.run_until_complete(createNewRoom("Default Chat #1", 3, "U-Psychpsyo", bySystem = True))
loop.run_until_complete(createNewRoom("Default Chat #2", 3, "U-Psychpsyo", bySystem = True))

# start websocket and listen
print("Starting websocket.")
start_server = websockets.serve(takeClient, "localhost", 32759)

loop.run_until_complete(start_server)
loop.run_forever()