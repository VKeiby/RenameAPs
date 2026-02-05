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

from ap_utils import (
    parse_and_rename_ap_data,
    process_single_ip,
    save_to_csv,
    sendShComm,
)

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
        net = "172.31."
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
    ip_list = [f"{ipAdd}{octet}" for octet in range(20, 14, -1)]

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
