#!/usr/bin/env python3
# This is test version with static IP
import datetime
import re
import socket
import time
from pprint import pprint

import paramiko


def sendShComm(
    ip,
    command,
    command1,
    command2,
    shSleep=0.2,
    maxRead=10000,
    longSleep=2,
    now=datetime.datetime.now(),
):
    USER = "admin"
    PASS = ""
    # report = "REP.AP_%.2i%.2i%i" % (now.year, now.month, now.day)
    report = f"REP.AP_{now:%y%m%d}"
    ff = open(report, "a")
    try:
        cl = paramiko.SSHClient()
        cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cl.connect(ip, username=USER, password=PASS, timeout=5)
    except socket.timeout:
        print(f"failed to connect to IP {ip}")
        return
    except paramiko.SSHException as error:
        print(f"error occurred {error} on ip {ip}")
        return
    except paramiko.ssh_exception.NoValidConnectionsError as error:
        print(f"error occurred {error} on ip {ip}")
        return

    with cl.invoke_shell() as ssh:
        ssh.send("ena\n")
        ssh.send(USER + "\n")
        ssh.send(PASS + "\n")
        time.sleep(shSleep)
        ###terminal lenght for no paging
        # ssh.send('skip\n')
        # time.sleep(shSleep)
        ###show config and write output
        # ssh.send('sh run\n')
        ssh.send(f"{command}\n")
        time.sleep(longSleep)
        ###Command2
        ssh.send(f"{command1}\n")
        time.sleep(longSleep)
        ###Command3 and write output
        ssh.send(f"{command2}\n")
        time.sleep(longSleep)
        output = ssh.recv(maxRead).decode("utf-8").replace("\r\n", "\n")
        # prompt = re.search()
        ff.write("\n" + ip + "\n")
        ff.write(output)
        ###show output config and write file with prefix, date and time
        print(output)
    ff.close()
    with open(report, "r") as f_read:
        with open("result.txt", "w") as f_write:
            f_write.write("---New AP---\n")
            for str in f_read:
                if str.startswith("172.16"):
                    f_write.write(str)
                elif str.startswith("device name"):
                    f_write.write(str)
                elif str.startswith("Serial"):
                    f_write.write(str)
                elif str.startswith("eth0"):
                    f_write.write(str)
                elif str.startswith("wlan0"):
                    f_write.write(str)
                elif str.startswith("wlan1"):
                    f_write.write(str)
                elif str.startswith("    SysName"):
                    f_write.write(str)
                elif str.startswith("    PortDescr"):
                    f_write.write(str)
                    f_write.write("\n")
    return output


if __name__ == "__main__":
    ###set date and time
    now = datetime.datetime.now()
    sitePrefix = """Citadel1 vl.11	--	1		Office          --  25
Citadel2 vl.11	--	2       TECOM.LV2.11	--	26          Tecom.LV1  vl.11 -  53
Al Khail vl.11	--	5       TECOM.LV2.12	-- 	27          Tecom.LV1  vl.12 -  54
Ejadah.RHB vl.11 -  7       TECOM.LV2.13	-- 	28          Tecom.LV1  vl.13 -  56
ECC-AlQuoz vl.11 -	8       Sawaeed vl.11	--	29          Tecom.LV1  vl.14 -  58
ECC-EO vl.11	--	9       Sawaeed vl.12	--	30          Tecom.LV5 vl.11  -- 60
ECC-EO vl.12	--	10      Sawaeed vl.13	--	31          Tecom.LV5 vl.12  -- 61
EMPTY       	--	12      Sawaeed vl.14	--	32          JAFZA-WEST vl.15 -	63
Office          --  13      JAFZA-WEST vl.11 -	36          JAFZA-WEST vl.16 -	64
Ejadah.PJA      --  15      ECC_SHJ2   vl.11 -	37          EMPTY            -- 65
Dubai Amblnc    --  16      Tecom.LV1A vl.11 -  39          EMPTY            -- 66
Ajman vl.11		--	17      Tecom.LV1A vl.12 -  43          EMPTY            -- 67
RAK vl.11		--	18      WideAdams  vl.11 -  46          Tecom.LV5 vl.13  -- 68
Sharjah vl.11	--	19      ECC-CAMP22 vl.11 -	47          Tecom.LV5 vl.14  -- 69
MGPI vl.11		--	21      JAFZA-WEST vl.12 -	49          Dry_Docks vl.11  -- 75
MGPI vl.12		--	22      JAFZA-WEST vl.13 -	50          Dry_Docks vl.12	 -- 76
MGPI vl.13		--	23      JAFZA-WEST vl.14 -	51          Dry_Docks vl.13	 -- 77
MGPI vl.14		--	24      WideAdams  vl.12 -  52          Dry_Docks vl.14	 -- 78




Input site prefix: """

    net = "172.31."
    ipPref = "99"
    ipAdd = net + ipPref
    octet = 16
    ###start FOR ...in
    while octet > 15:
        octet -= 1
        ip = ipAdd + "." + str(octet)
        # print(ip)
        out = sendShComm(ip, "get device-name", "get boarddata", "get lldp neighbors")
        pprint(out, width=120)
        # print(out)
