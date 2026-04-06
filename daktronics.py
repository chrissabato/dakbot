# //////////////////////////////////////////////////////////////////////////////////////////////////////////////////
# Title: scoredata
# Author: Alex Riviere (github.com/fimion)
# Date: 2017
# Availability: https://github.com/chrisdeely/scoredata/blob/master/python/daktronics.py
# \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\

global dakSports

import serial
class Daktronics(object):
    def __init__(self, dakSport, com=None):
        if com != None:
            self.Serial = serial.Serial(com, 19200)
        else:
            self.Serial = serial.Serial("COM1", 19200)
        self.header = b''
        self.code = b''
        self.rtd = b''
        self.checksum = b''
        self.text = b''
        self.sport = dakSport
        self.dakString = " " * self.sport['dakSize'][1]

    def update(self):
        c = b''
        self.rtd = b''
        while c != b'\x16':
            c = self.Serial.read()
            #print(c)
        c = b'\x16'
        while c != b'\x17':
            c = self.Serial.read()
            self.rtd += c
            #print(c)

        self.header = self.rtd.partition(b'\x16')[2].partition(b'\x01')[0]
        self.code = self.rtd.partition(b'\x01')[2].partition(b'\x02')[0].partition(b'\x04')[0]
        self.text = self.rtd.partition(b'\x02')[2].partition(b'\x04')[0]
        self.checksum = self.rtd.partition(b'\x04')[2].partition(b'\x17')[0]
        #print("binary:",self.header, self.code, self.text, self.checksum)

        code = self.code.decode()
        code = code[-4:]
        text = self.text.decode()
        #print("code:",code)
        #print("text:",text)
        self.dakString = self.dakString[:int(code)] + text + self.dakString[int(code)+len(text):]

    def __getitem__(self, gikey):
        if gikey in self.sport:
            return self.dakString[self.sport[gikey][0]-1:self.sport[gikey][1]+self.sport[gikey][0]-1]
        return ""
