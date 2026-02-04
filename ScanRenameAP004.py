#!/usr/bin/env python3
import csv
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pprint import pprint

import paramiko
from dotenv import load_dotenv

# Загружаем .env
load_dotenv()

# Конфигурация из .env с дефолтами
USER = os.getenv("DEVICE_USERNAME", "admin")
PASS = os.getenv("DEVICE_PASSWORD")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "5"))
DEFAULT_PREFIX = os.getenv("DEFAULT_SITE_PREFIX")

# Проверка обязательных переменных
if not PASS:
    print("Ошибка: переменная DEVICE_PASSWORD не найдена в .env")
    exit(1)
if not USER:
    print(
        "Ошибка: переменная DEVICE_USERNAME не найдена в .env (использован default 'admin')"
    )

# ────────────────────────────────────────────────
# Основная функция подключения и выполнения команд
# ────────────────────────────────────────────────


def sendShComm(
    ip,
    commands,
    now=None,
    new_name=None,
    dry_run=True,
    shSleep=0.8,
    longSleep=4.0,
    maxRead=32768,
):
    if now is None:
        now = datetime.now()

    report = f"REP.AP_{now:%y%m%d}.txt"
    output = ""
    cl = None

    try:
        cl = paramiko.SSHClient()
        cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cl.connect(
            ip,
            username=USER,
            password=PASS,
            timeout=10,
            allow_agent=False,
            look_for_keys=False,
            banner_timeout=15,
            auth_timeout=15,
        )

        with cl.invoke_shell(width=200, height=500) as ssh:
            time.sleep(shSleep * 2)

            # Авторизация
            initial = ""
            start = time.time()
            while time.time() - start < 8:
                if ssh.recv_ready():
                    initial += ssh.recv(maxRead).decode("utf-8", errors="replace")
                time.sleep(0.2)
                if "Please login:" in initial:
                    break

            ssh.send(f"{USER}\n")
            time.sleep(shSleep)
            ssh.send(f"{PASS}\n")
            time.sleep(shSleep * 1.5)

            auth_resp = ""
            start = time.time()
            while time.time() - start < 8:
                if ssh.recv_ready():
                    auth_resp += ssh.recv(maxRead).decode("utf-8", errors="replace")
                time.sleep(0.2)
                if "rkscli:" in auth_resp.lower():
                    break

            output += auth_resp

            # Выполнение команд чтения
            for cmd in commands:
                ssh.send(f"{cmd}\n")
                time.sleep(longSleep)
                cmd_out = ""
                timeout = time.time() + 20
                while time.time() < timeout:
                    if ssh.recv_ready():
                        cmd_out += ssh.recv(maxRead).decode("utf-8", errors="replace")
                    time.sleep(0.15)
                    if "rkscli:" in cmd_out.lower() or len(cmd_out) > 500:
                        break
                output += f"\n--- {cmd} ---\n{cmd_out.strip()}\n"

            # Переименование, если указано
            if new_name:
                print(f"[{ip}] Установка имени → {new_name}")
                if dry_run:
                    print(f"[{ip}] DRY-RUN: переименование не выполнено")
                else:
                    ssh.send(f"set device-name {new_name}\n")
                    time.sleep(longSleep)

                    set_out = ""
                    timeout = time.time() + 10
                    while time.time() < timeout:
                        if ssh.recv_ready():
                            set_out += ssh.recv(maxRead).decode(
                                "utf-8", errors="replace"
                            )
                        time.sleep(0.1)
                        if "OK" in set_out or "rkscli:" in set_out.lower():
                            break
                    print(f"[{ip}] set → {set_out.strip()}")

                    # Проверка
                    ssh.send("get device-name\n")
                    time.sleep(longSleep)
                    check_out = ""
                    timeout = time.time() + 10
                    while time.time() < timeout:
                        if ssh.recv_ready():
                            check_out += ssh.recv(maxRead).decode(
                                "utf-8", errors="replace"
                            )
                        time.sleep(0.1)
                        if "rkscli:" in check_out.lower():
                            break
                    print(f"[{ip}] Текущее имя: {check_out.strip()}")
                    output += f"\n--- После переименования ---\n{check_out.strip()}\n"

            # Лог в файл
            with open(report, "a", encoding="utf-8") as ff:
                ff.write(f"\n=== {ip} ===\n{output}\n")

    except Exception as e:
        print(f"[{ip}] Ошибка: {type(e).__name__}: {e}")
        return None
    finally:
        if cl:
            cl.close()

    return output


# ────────────────────────────────────────────────
# Парсер данных AP с фильтрацией/обновлением порта
# ────────────────────────────────────────────────


def parse_and_rename_ap_data(output: str, ip: str) -> dict:
    data = {
        "ip": ip,
        "original_device_name": "",
        "new_device_name": "",
        "port": "",
        "model": "",
        "serial": "",
        "base_mac": "",
        "status": "Не обработано",
    }

    lines = output.splitlines()
    for line in lines:
        line = line.strip()
        if line.startswith("device name :"):
            m = re.search(r"device name\s*:\s*['\"]?([^'\"]+)['\"]?", line)
            if m:
                data["original_device_name"] = m.group(1).strip()
        elif "PortDescr:" in line:
            m = re.search(r"PortDescr:\s*GigabitEthernet1/1/(\d+)", line, re.I)
            if m:
                data["port"] = m.group(1)
        elif line.startswith("name:"):
            data["model"] = line.split(":", 1)[1].strip()
        elif "Serial#:" in line:
            data["serial"] = line.split(":", 1)[1].strip()
        elif "base" in line.lower() and ":" in line:
            m = re.search(r"base\s*[^:]*:\s*([^,]+)", line, re.I)
            if m:
                data["base_mac"] = m.group(1).strip()

    original_name = data["original_device_name"]
    real_port = data["port"]

    if original_name and real_port:
        match_existing = re.search(r"_SP(\d{1,2})$", original_name)
        if match_existing:
            existing_port = match_existing.group(1)
            if existing_port == real_port:
                data["new_device_name"] = original_name
                data["status"] = "Уже OK (порт совпадает)"
            else:
                base_name = re.sub(r"_SP\d{1,2}$", "", original_name).rstrip("_")
                data["new_device_name"] = f"{base_name}_SP{real_port}"
                data["status"] = "Обновление порта (несовпадение)"
        else:
            data["new_device_name"] = f"{original_name}_SP{real_port}"
            data["status"] = "Добавление порта"
    else:
        data["new_device_name"] = original_name or "UNKNOWN"
        data["status"] = "Порт/имя не найдены"

    return data


# ────────────────────────────────────────────────
# Сохранение отчёта
# ────────────────────────────────────────────────


def save_to_csv(results: list[dict], filename="ap_rename_report.csv"):
    if not results:
        print("Нет данных для сохранения")
        return
    headers = [
        "ip",
        "original_device_name",
        "new_device_name",
        "port",
        "model",
        "serial",
        "base_mac",
        "status",
    ]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nОтчёт сохранён → {filename} ({len(results)} устройств)")


# ────────────────────────────────────────────────
# Функция для обработки одного IP (для потоков)
# ────────────────────────────────────────────────


def process_single_ip(ip, read_commands, now, REAL_CHANGE):
    try:
        full_output = sendShComm(
            ip, read_commands, now=now, new_name=None, dry_run=True
        )

        if not full_output:
            return None, "Нет соединения"

        parsed = parse_and_rename_ap_data(full_output, ip)

        if not parsed["port"]:
            return None, "Порт не найден"

        new_name = parsed["new_device_name"]

        if parsed["status"].startswith("Уже OK"):
            print(f"[{ip}] Пропуск: порт уже правильный")
            parsed["status"] += " (пропущено)"
            return parsed, None

        sendShComm(ip, [], now=now, new_name=new_name, dry_run=not REAL_CHANGE)

        parsed["status"] += " (изменено)" if REAL_CHANGE else " (dry-run)"
        return parsed, None

    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ────────────────────────────────────────────────
# Главная логика
# ────────────────────────────────────────────────

if __name__ == "__main__":
    now = datetime.now()
    read_commands = ["get device-name", "get boarddata", "get lldp neighbors"]

    sitePrefix = """Citadel1 vl.11 -- 1 Office -- 25
Citadel2 vl.11-- 2 TECOM.LV2.11 -- 26 Tecom.LV1 vl.11 - 53
Al Khail vl.11-- 5 TECOM.LV2.12 -- 27 Tecom.LV1 vl.12 - 54
Ejadah.RHB vl.11-- 7 TECOM.LV2.13 -- 28 Tecom.LV1 vl.13 - 56
ECC-AlQuoz vl.11-- 8 Sawaeed vl.11 -- 29 Tecom.LV1 vl.14 - 58
ECC-EO vl.11 -- 9 Sawaeed vl.12 -- 30 Tecom.LV5 vl.11 -- 60
ECC-EO vl.12 -- 10 Sawaeed vl.13 -- 31 Tecom.LV5 vl.12 -- 61
EMPTY -- 12 Sawaeed vl.14 -- 32 JAFZA-WEST vl.15 - 63
Office -- 13 JAFZA-WEST vl.11 - 36 JAFZA-WEST vl.16 - 64
Ejadah.PJA -- 15 ECC_SHJ2 vl.11 - 37 EMPTY -- 65
Dubai Amblnc -- 16 Tecom.LV1A vl.11 - 39 EMPTY -- 66
Ajman vl.11 -- 17 Tecom.LV1A vl.12 - 43 EMPTY -- 67
RAK vl.11 -- 18 WideAdams vl.11 - 46 Tecom.LV5 vl.13 -- 68
Sharjah vl.11 -- 19 ECC-CAMP22 vl.11 - 47 Tecom.LV5 vl.14 -- 69
MGPI vl.11 -- 21 JAFZA-WEST vl.12 - 49 Dry_Docks vl.11 -- 75
MGPI vl.12 -- 22 JAFZA-WEST vl.13 - 50 Dry_Docks vl.12 -- 76
MGPI vl.13 -- 23 JAFZA-WEST vl.14 - 51 Dry_Docks vl.13 -- 77
MGPI vl.14 -- 24 WideAdams vl.12 - 52 Dry_Docks vl.14 -- 78

Input site prefix: """

    ipPref = input(sitePrefix).strip()
    if not ipPref and DEFAULT_PREFIX:
        ipPref = DEFAULT_PREFIX
        print(f"Использован префикс из .env: {DEFAULT_PREFIX}")

    try:
        ipPref = int(ipPref)
        net = "172.16."
        ipAdd = f"{net}{ipPref}."
    except ValueError:
        print("Ошибка: введите целое число (например 17)")
        exit(1)

    REAL_CHANGE = False  # ← Поменяй на True только после всех тестов!

    results = []
    errors = []

    print(f"\n=== Сканирование пула {ipAdd}2 – {ipAdd}254 ===")
    print(f"Режим: {'РЕАЛЬНОЕ ПЕРЕИМЕНОВАНИЕ' if REAL_CHANGE else 'DRY-RUN'}")
    print(f"Дата: {now:%Y-%m-%d %H:%M}\n")

    # Генерируем список IP
    ip_list = [f"{ipAdd}{octet}" for octet in range(254, 1, -1)]

    # Запускаем пул потоков
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_ip = {
            executor.submit(process_single_ip, ip, read_commands, now, REAL_CHANGE): ip
            for ip in ip_list
        }

        for future in as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                parsed, error = future.result()
                if parsed:
                    results.append(parsed)
                if error:
                    errors.append((ip, error))
                    print(f"[{ip}] Ошибка: {error}")
            except Exception as e:
                errors.append((ip, str(e)))
                print(f"[{ip}] Критическая ошибка: {e}")

    save_to_csv(results)

    if errors:
        print("\nОшибки:")
        for ip, msg in errors:
            print(f"  {ip}: {msg}")

    print(f"\nГотово. Обработано {len(results)} устройств, ошибок: {len(errors)}")
