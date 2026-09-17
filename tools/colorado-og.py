import serial,binascii,json,copy
SerialPort = "/dev/ttyUSB0"
DATA_DIR = ""

DIR = ""    

# ====================================
# Initializing variables
# ====================================
ShowTime = False
LaneAddress = False

data = 0
Channel = 0
sub = 0
Segment = 0

EVENT_NUM = 0
HEAT_NUM = 0

HIDE_TIME = True
RunningTime = ''
DisplayLine=''



# ====================================
# Saves current scoreboard to file
# ====================================
def saveScoreboard(TIME):
    print("SAVING SCOREBOARD")
    TMP_TIME = copy.deepcopy(TIME)
    TMP_TIME.pop(0)
    TIMES=[]
    header = ["Lane","Place","Time","PlaceBG","PlaceBGAlt"]
    
    for lane in TMP_TIME:

        if lane[2] == "" or lane[1] == "":
            lane.append(DIR+"clear-bkgd.png")
            lane.append(DIR+"clear-bkgd.png")
            lane[1] = ""
            lane[2] = ""
        else:
            lane.append(DIR+"bonus-bkgd.png")
            lane.append(DIR+"grey-bkgd.png")

        TIMES.append(dict(zip(header, lane)))
   
    with open(DATA_DIR+"data-times.json", "w") as outfile:
        json.dump(TIMES, outfile, indent=4)



# ====================================
# Saves current clock to file
# ====================================
def saveClock(currentClock):
    if len(currentClock) == 1:
        currentClock = "0:0"+currentClock
    elif len(currentClock) == 2:
        currentClock = "0:"+currentClock
    print(currentClock)
    try:
        with open(DATA_DIR+"data-clock.txt", "w") as f:
            f.write(currentClock)
    except:
        pass

# ====================================
# Saves current Event info to file
# ====================================
def saveCurrentEvent(EVENT_NUM,HEAT_NUM):
    print("==================")
    print("NEW EVENT: ",EVENT_NUM,HEAT_NUM )
    print("==================\n")

    info = [{"EventNumber":EVENT_NUM,"HeatNumber":HEAT_NUM}]
    with open(DATA_DIR+"data-event.json", "w") as outfile:
        json.dump(info, outfile, indent=4)


# ====================================
# initialize TIME Dict
# ====================================
def resetTIME():
    temp = [[''] * 3 for i in range(7)]
    for line in range(7):
        temp[line][0] = str(line)
    saveScoreboard(temp)
    return temp

# ====================================
# initialize Display Dict
# ====================================
Display = [[' '] * 8 for i in range(32)]
TIME = resetTIME()



try:
    ser = serial.Serial(SerialPort, 9600, timeout = 1)
except Exception:
    exit("Error Opening " + SerialPort)

try:
    byte = ser.read()
    while byte != None:
        if byte != b'':

            ascii=binascii.b2a_hex(byte).decode()
            byteIntVal = int( ascii,16)
            # ---------------------------------------------------------------
            # Determine if Module Address
            # ----------------------------------------------------------------------
            if byteIntVal > 127:
                # Determine if Lane is Enabled and Running
                if byteIntVal > 190:
                    ShowTime  = False;
                else:
                    ShowTime  = True;
                
                # Determine if Lane Address, only thru Lane 10
                if byteIntVal > 169 and byteIntVal < 190:
                    LaneAddress = True;
                else:
                    LaneAddress = False;

                # Determine type Data = 0(even) or Format = 1(odd)
                sub = byteIntVal & 0x01;
                
                # Address index
                Channel = ((byteIntVal >> 1) & 0x1f) ^ 0x1f;
                
                

            # ---------------------------------------------------------------
            # Extract Data for each Segment Data, not Format
            # ----------------------------------------------------------------------
            if (byteIntVal < 128 and sub == 0):
                # Determine which segment the data's for
                Segment = (byteIntVal & 0xf0) >> 4;

                # Extract the data for the segment
                data = (((byteIntVal << 4) & 0xf0)) >> 4;

                # Determine if Data is to be Displayed, this is done before the XOR
                if (Channel >= 0 and data == 0x00):
                    data = " "
                else:
                    data = data ^ 0x0f;
                Display[Channel][Segment] = data;

            
            # ---------------------------------------------------------------
            # Blank out Lane info After Start or Split Display
            # ---------------------------------------------------------------
            if not ShowTime:
                # Show lane number but blank out everything else
                for i in range(1,8):
                    Display[Channel][i] = " " # Space
                if Channel < 7:
                    TIME[Channel][2]=""
                    TIME[Channel][1]=""
                
            if LaneAddress:
                # Determine if Lane is OFF from Console 
                if (Display[Channel][0] == " "):
                    # Totally Blank Lane if OFF from Console
                    for i in range(0, 8):
                        Display[Channel][i] = " " # Space



            # ---------------------------------------------------------------

            if Channel == 12:
                tmpEvent = (str(Display[12][1]) + str(Display[12][2])).strip()
                tmpHeat = (str(Display[12][6]) + str(Display[12][7])).strip()
            
                if EVENT_NUM != tmpEvent or HEAT_NUM != tmpHeat:
                    EVENT_NUM = tmpEvent
                    HEAT_NUM = tmpHeat
                    TIME = resetTIME()
                    
                    if HEAT_NUM != '' and EVENT_NUM != '':
                        saveCurrentEvent(EVENT_NUM,HEAT_NUM)
     
                    
            # ---------------------------------------------------------------
            # Running Time
            # ---------------------------------------------------------------
            
            Min10 = str(Display[0][2])
            Min01 = str(Display[0][3])
            Sec10 = str(Display[0][4])
            Sec01 = str(Display[0][5])
            if Sec01 != " ":
                if Min01!= " ":
                    RunningTime = (Min10+Min01 +":"+Sec10 + Sec01).strip()
                else:
                    RunningTime = (Sec10 + Sec01).strip()
            if TIME[0][2] != RunningTime:
                TIME[0][2] = RunningTime
                
                if TIME[0][2].find(" ") < 0:  
                    saveClock(TIME[0][2])
                    

            # ---------------------------------------------------------------
            # Lane Times
            # ---------------------------------------------------------------

            if 0 <= Channel <= 6:
            #for ln in range(1,7):
                ln = Channel
                Min10 = str(Display[ln][2])
                Min01 = str(Display[ln][3])
                Sec10 = str(Display[ln][4])
                Sec01 = str(Display[ln][5])
                Ten10 = str(Display[ln][6])
                Ten01 = str(Display[ln][7])

                if Ten01 != " ":

                    if Min01!= " ":
                        tmp = (Min10+Min01 +":"+Sec10 + Sec01 +"."+Ten10 + Ten01).strip()    
                    else:
                        tmp = (Sec10 + Sec01 +"."+Ten10 + Ten01).strip()

                    TIME[ln][0] = str(Display[ln][0]).strip()
                    TIME[ln][1] = str(Display[ln][1]).strip()
                    if TIME[ln][2] != tmp:
                        # Update Time
                        TIME[ln][2] = tmp
                        if not HIDE_TIME:
                            saveScoreboard(TIME)
                if Min10+Min01 + Sec10 + Sec01 +Ten10 + Ten01 == "      ":
                    tmp=''
                    if TIME[ln][2] != tmp:
                        TIME[ln][2]=""
                        if not HIDE_TIME:
                            saveScoreboard(TIME)
                
            tmp='' 
            for ln in range(1,7):
                tmp = tmp + TIME[ln][2] + "   "
            tmp = tmp.strip()
            if DisplayLine != tmp:
                DisplayLine = tmp
                #show scoreboard times
                print(DisplayLine)
                #if not HIDE_TIME:
                saveScoreboard(TIME)



        # ================================
        # Read the next byteIntVal
        # ================================
        byte = ser.read()
        


except KeyboardInterrupt:
    print('interrupted!')
