
import json, datetime, argparse
from daktronics import Daktronics

parser = argparse.ArgumentParser()
parser.add_argument("-init",action="store_true", default=False, help="Initialize saved json file")
args = parser.parse_args()


# Load setup data
SETTINGS = json.load(open("settings.json"))
dakSport = json.load(open("daksports.json"))[SETTINGS["SPORT"]]
dak = Daktronics(dakSport, SETTINGS["COM_PORT"])

# ======================================================
# initialize
# ======================================================
def initialize():
        DATA = {}
        for key in dakSport:
                DATA[key]=""
        DATA['AwayTeamScore'] ="0"
        DATA["AwayAtBat"] = ">"
        DATA['HomeTeamScore'] ="0"
        DATA["InningText"] = "1ST"
        DATA["Ball"] ="0"
        DATA["Strike"]="0"
        DATA["Out"] ="0"
        DATA["Outs"] ="□□□"
        DATA["Count"]="0-0"
        DATA['TB'] = "▲"
        DATA['top'] = ""
        DATA['bottom'] = ""
        with open('ScoreBoardData.json', 'w') as f:
                json.dump([DATA] , f, indent=4, sort_keys=True)


def outs(out):
        if out == "3":
                return "⚫⚫⚫"
        if out == "2":
                return "⚫⚫⚪"
        if out == "1":
                return "⚫⚪⚪"
        if out == "0":
                return "⚪⚪⚪"
        return ""
def TB(tb):
        if "bot" in tb.lower():
                return "▼"
        else:
                return "▲"



# ======================================================
# Convert Dak object to json
# ======================================================
def dak2json(dak):
        global dakSport
        tmp={}
        for key in dakSport:
                tmp[key]=dak[key].strip()

        tmp["HomeAtBat"] = tmp["HomeAtBat"].replace("<",">")
        tmp["Count"] = tmp["Ball"] + "-" +tmp["Strike"]
        if tmp["Count"] == "-":
                tmp["Count"] = ""
                
        tmp["Outs"] = outs(tmp["Out"])
        tmp["TB"] = TB(tmp["InningDescription"])

        tmp["top"] = "▲" if  tmp["TB"] == "▲" else ""
        tmp["bottom"] = "▼" if  tmp["TB"] == "▼" else ""


        try:
                with open('ScoreBoardData-New.json', 'w') as f2:
                        json.dump([tmp], f2, indent=4, sort_keys=True)
        except:
                print("Error Writting ScoreBoardData-New.json")
                
        return tmp

# ======================================================
# scorebug
# ======================================================
def scorebug(dak):
        with open('ScoreBoardData.json') as json_file:
                saveddata = json.load(json_file)[0]

        DATA = dak2json(dak)

        # Import saved data into new data
        for key in DATA:
                if key not in ['AwayAtBat','HomeAtBat']:
                        if DATA[key] == "":
                                DATA[key] = saveddata[key]

        if DATA != saveddata:
                ## NEW DATA
                try:
                        with open('ScoreBoardData.json', 'w') as f2:
                                json.dump([DATA], f2, indent=4, sort_keys=True)
                except:
                        print("Error Writting ScoreBoardData.json")

                                
                print("\n\n\n\n\n\n\n")
                print(" ╔══════════════╗")
                dt = datetime.datetime.now()
                print(dt.strftime(" ║   %H:%M:%S   ║"))
                print(" ╠════════╦═════╣")
                print(" ║ AWAY "+ DATA['AwayAtBat'].ljust(1)+" ║  " + DATA['AwayTeamScore'].rjust(2) + " ║")
                print(" ║ HOME "+ DATA['HomeAtBat'].ljust(1)+" ║  " + DATA['HomeTeamScore'].rjust(2) + " ║")
                print(" ║ INNING ║ " + DATA["InningText"].rjust(3) + " ║")
                print(" ║ OUTS   ║ " + DATA["Outs"].rjust(3) + " ║")
                print(" ║ COUNT  ║ " + DATA["Count"].rjust(3) + " ║")
                print(" ╚════════╩═════╝")
        





print("\n\n\n\n")
print(" ╔══════════════════╗")
print(" ║  Program Started ║")

if args.init:
        print(" ║   Initializing   ║")
        initialize()

print(" ╚══════════════════╝")       

while True:  
    

    try:
            dak.update()
            scorebug(dak)
            
    except KeyboardInterrupt:
            print("\n\n\n\n")
            print(" ╔══════════════════╗")
            print(" ║  Program Halted  ║")
            print(" ╚══════════════════╝") 
            break
    
    except:
            print("error")