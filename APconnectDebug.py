import datetime
import socket
import time

import paramiko


def sendShComm(ip, commands, now, shSleep=0.8, longSleep=4.0, maxRead=32768):
    USER = "admin"
    PASS = "bsquared2019!@#"
    report = f"REP.AP_{now:%y%m%d}.txt"

    output = ""
    cl = None
    try:
        print(f"[DEBUG] Подключаемся к {ip}...")
        cl = paramiko.SSHClient()
        cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cl.connect(
            ip,
            username=USER,  # пробуем передать здесь
            password=PASS,
            timeout=10,
            allow_agent=False,
            look_for_keys=False,
            banner_timeout=15,
            auth_timeout=15,
        )
        print("[DEBUG] connect() прошёл успешно")

        with cl.invoke_shell(width=200, height=500) as ssh:
            time.sleep(shSleep * 2)  # даём время на первое приглашение

            # ──────────────── ПОЛНЫЙ ДЕБАГ ────────────────
            print("[DEBUG] Читаем начальный баннер / приглашение...")
            initial = ""
            start = time.time()
            while time.time() - start < 8:
                if ssh.recv_ready():
                    chunk = ssh.recv(maxRead).decode("utf-8", errors="replace")
                    initial += chunk
                    print(f"[RAW CHUNK] {repr(chunk)}")  # ← самый важный дебаг!
                time.sleep(0.2)
                if "rkscli:" in initial or "password" in initial.lower():
                    break

            output += initial
            print(f"[DEBUG] Initial полный:\n{initial.rstrip()}")

            # Если видим приглашение на логин — отвечаем
            if "Please login:" in initial or "login as:" in initial:
                print("[DEBUG] Отправляем логин...")
                ssh.send(f"{USER}\n")
                time.sleep(shSleep)

                # Читаем после логина (должно быть password :)
                login_resp = ""
                start = time.time()
                while time.time() - start < 6:
                    if ssh.recv_ready():
                        chunk = ssh.recv(maxRead).decode("utf-8", errors="replace")
                        login_resp += chunk
                        print(f"[RAW после логина] {repr(chunk)}")
                    time.sleep(0.15)
                    if "password" in login_resp.lower():
                        break

                print(f"[DEBUG] После логина:\n{login_resp.rstrip()}")

                # Отправляем пароль
                print("[DEBUG] Отправляем пароль...")
                ssh.send(f"{PASS}\n")
                time.sleep(shSleep * 1.5)

                # Читаем приветствие / prompt
                auth_resp = ""
                start = time.time()
                while time.time() - start < 8:
                    if ssh.recv_ready():
                        chunk = ssh.recv(maxRead).decode("utf-8", errors="replace")
                        auth_resp += chunk
                        print(f"[RAW после пароля] {repr(chunk)}")
                    time.sleep(0.2)
                    if "rkscli:" in auth_resp or "Copyright" in auth_resp:
                        break

                output += auth_resp
                print(f"[DEBUG] После авторизации:\n{auth_resp.rstrip()}")

            # ──────────────── Выполняем команды ────────────────
            for cmd in commands:
                print(f"[DEBUG] Отправляем команду: {cmd}")
                ssh.send(f"{cmd}\n")
                time.sleep(longSleep)

                cmd_out = ""
                timeout = time.time() + 20
                while time.time() < timeout:
                    if ssh.recv_ready():
                        chunk = ssh.recv(maxRead).decode("utf-8", errors="replace")
                        cmd_out += chunk
                        print(f"[RAW {cmd}] {repr(chunk)}")
                    time.sleep(0.15)
                    if "rkscli:" in cmd_out.lower() or len(cmd_out) > 200:
                        break

                output += f"\n--- {cmd} ---\n{cmd_out.strip()}\n"
                print(f"[DEBUG] Вывод {cmd}:\n{cmd_out.strip()}\n")

            with open(report, "a", encoding="utf-8") as ff:
                ff.write(f"\n=== {ip} ===\n{output}\n")

    except Exception as e:
        print(f"[ОШИБКА {ip}] {type(e).__name__}: {e}")
    finally:
        if cl:
            cl.close()

    return output


if __name__ == "__main__":
    now = datetime.datetime.now()
    commands = ["get device-name", "get boarddata", "get lldp neighbors"]
    test_ip = "172.31.99.15"
    print(f"Проверка {test_ip}...")
    sendShComm(test_ip, commands, now)
