#!/usr/bin/env python3
import csv
import datetime
import re

# import socket
import time
from datetime import datetime

import paramiko


def sendShComm(ip, commands, now, shSleep=0.8, longSleep=4.0, maxRead=32768):
    """
    Подключение к Ruckus Unleashed AP и выполнение списка команд.
    Авторизация внутри shell (логин + пароль вручную).
    """
    USER = "admin"
    PASS = "bsquared2019!@#"  # ← В продакшене спрячь в .env или os.getenv()
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
            time.sleep(shSleep * 2)  # ждём первое приглашение

            # Читаем начальный баннер / Please login:
            initial = ""
            start = time.time()
            while time.time() - start < 8:
                if ssh.recv_ready():
                    chunk = ssh.recv(maxRead).decode("utf-8", errors="replace")
                    initial += chunk
                time.sleep(0.2)
                if "Please login:" in initial:
                    break

            # Отправляем логин
            ssh.send(f"{USER}\n")
            time.sleep(shSleep)

            # Ждём password :
            time.sleep(shSleep)
            ssh.send(f"{PASS}\n")
            time.sleep(shSleep * 1.5)

            # Читаем приветствие после авторизации
            auth_resp = ""
            start = time.time()
            while time.time() - start < 8:
                if ssh.recv_ready():
                    chunk = ssh.recv(maxRead).decode("utf-8", errors="replace")
                    auth_resp += chunk
                time.sleep(0.2)
                if "rkscli:" in auth_resp.lower():
                    break

            output += auth_resp

            # Выполняем команды
            for cmd in commands:
                ssh.send(f"{cmd}\n")
                time.sleep(longSleep)

                cmd_out = ""
                timeout = time.time() + 20
                while time.time() < timeout:
                    if ssh.recv_ready():
                        chunk = ssh.recv(maxRead).decode("utf-8", errors="replace")
                        cmd_out += chunk
                    time.sleep(0.15)
                    if "rkscli:" in cmd_out.lower() or len(cmd_out) > 500:
                        break

                output += f"\n--- {cmd} ---\n{cmd_out.strip()}\n"

            # Запись в отчёт
            with open(report, "a", encoding="utf-8") as ff:
                ff.write(f"\n=== {ip} ===\n{output}\n")

    except Exception as e:
        print(f"[{ip}] Ошибка: {type(e).__name__}: {e}")
        return None
    finally:
        if cl:
            cl.close()

    return output


def parse_and_rename_ap_data(output: str, ip: str) -> dict:
    """
    Парсит ключевые поля из вывода Ruckus AP и переименовывает device name.
    Возвращает словарь с обработанными данными или None при ошибке.
    """
    data = {
        "ip": ip,
        "original_device_name": "",
        "new_device_name": "",
        "port": "",
        "model": "",
        "serial": "",
        "base_mac": "",
    }

    lines = output.splitlines()

    for line in lines:
        line = line.strip()

        # device name
        if line.startswith("device name :"):
            match = re.search(r"device name\s*:\s*['\"]?([^'\"]+)['\"]?", line)
            if match:
                data["original_device_name"] = match.group(1).strip()

        # PortDescr → ищем GigabitEthernet...
        elif "PortDescr:" in line:
            match = re.search(
                r"PortDescr:\s*GigabitEthernet1/1/(\d+)", line, re.IGNORECASE
            )
            if match:
                data["port"] = match.group(1)

        # name: (модель)
        elif line.startswith("name:"):
            data["model"] = line.split(":", 1)[1].strip()

        # Serial#
        elif "Serial#:" in line:
            data["serial"] = line.split(":", 1)[1].strip()

        # base MAC (из строки V54 MAC Address Pool или wlan0/wlan1/eth0)
        elif "base" in line.lower() and ":" in line:
            # берём первое упоминание MAC после "base"
            match = re.search(r"base\s*[^:]*:\s*([^,]+)", line, re.IGNORECASE)
            if match:
                data["base_mac"] = match.group(1).strip()

    # Формируем новое имя, если есть порт и оригинальное имя
    if data["original_device_name"] and data["port"]:
        data["new_device_name"] = f"{data['original_device_name']}_SP{data['port']}"
    else:
        data["new_device_name"] = data["original_device_name"] or "UNKNOWN"

    return data


def save_to_csv(results: list[dict], filename="ap_devices.csv"):
    """Сохраняет список словарей в CSV"""
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
    ]

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(results)

    print(f"Сохранено {len(results)} устройств → {filename}")


if __name__ == "__main__":
    import sys

    now = datetime.now()
    read_commands = ["get device-name", "get boarddata", "get lldp neighbors"]

    sitePrefix = """Citadel1 vl.11	--	1		Office          --  25
    Citadel2 vl.11--	2       TECOM.LV2.11	--  26          Tecom.LV1  vl.11 -  53
    Al Khail vl.11--	5       TECOM.LV2.12	--  27          Tecom.LV1  vl.12 -  54
    Ejadah.RHB vl.11--	7       TECOM.LV2.13	--  28          Tecom.LV1  vl.13 -  56
    ECC-AlQuoz vl.11--	8       Sawaeed vl.11	--  29          Tecom.LV1  vl.14 -  58
    ECC-EO vl.11    --	9       Sawaeed vl.12	--  30          Tecom.LV5 vl.11  -- 60
    ECC-EO vl.12    --	10      Sawaeed vl.13	--  31          Tecom.LV5 vl.12  -- 61
    EMPTY           --	12      Sawaeed vl.14	--  32          JAFZA-WEST vl.15 -  63
    Office          --  13      JAFZA-WEST vl.11 -  36          JAFZA-WEST vl.16 -  64
    Ejadah.PJA      --  15      ECC_SHJ2   vl.11 -  37          EMPTY            -- 65
    Dubai Amblnc    --  16      Tecom.LV1A vl.11 -  39          EMPTY            -- 66
    Ajman vl.11	    --	17      Tecom.LV1A vl.12 -  43          EMPTY            -- 67
    RAK vl.11	    --	18      WideAdams  vl.11 -  46          Tecom.LV5 vl.13  -- 68
    Sharjah vl.11   --	19      ECC-CAMP22 vl.11 -  47          Tecom.LV5 vl.14  -- 69
    MGPI vl.11	    --	21      JAFZA-WEST vl.12 -  49          Dry_Docks vl.11  -- 75
    MGPI vl.12	    --	22      JAFZA-WEST vl.13 -  50          Dry_Docks vl.12	 -- 76
    MGPI vl.13	    --	23      JAFZA-WEST vl.14 -  51          Dry_Docks vl.13	 -- 77
    MGPI vl.14	    --	24      WideAdams  vl.12 -  52          Dry_Docks vl.14	 -- 78




    Input site prefix: """

    net = "172.16."
    ipPref = input(sitePrefix)
    ipAdd = net + ipPref
    octet = 255
    ###start FOR ...in
    while octet > 1:
        octet -= 1
        ip = ipAdd + "." + str(octet)
        # print(ip)
        out = sendShComm(ip, "get device-name", "get boarddata", "get lldp neighbors")
        pprint(out, width=120)
        # print(out)

    # Флаг: True = только симуляция, False = реальное изменение
    REAL_CHANGE = False  # ← поменяй на True ТОЛЬКО после тестов!

    results = []
    errors = []

    print(
        f"\n=== Массовое переименование AP ({'DRY-RUN' if not REAL_CHANGE else 'РЕАЛЬНОЕ ИЗМЕНЕНИЕ'}) ==="
    )
    print(f"Дата отчёта: {now:%Y-%m-%d %H:%M}")
    print(f"Всего IP в списке: {len(ip_list)}\n")

    for ip in ip_list:
        print(f"\nОбработка {ip}...")

        try:
            # 1. Читаем текущее состояние
            full_output = sendShComm(
                ip,
                read_commands,
                now=now,
                new_name=None,  # сначала только чтение
                dry_run=True,  # чтение всегда безопасно
            )

            if not full_output:
                errors.append((ip, "Не удалось получить вывод"))
                continue

            # 2. Парсим данные
            parsed = parse_and_rename_ap_data(full_output, ip)

            if not parsed or not parsed["port"]:
                errors.append((ip, "Не удалось определить порт или имя"))
                continue

            new_name = parsed["new_device_name"]
            print(f"  Предлагаемое имя: {new_name}")

            # 3. Выполняем изменение (или dry-run)
            change_output = sendShComm(
                ip,
                [],  # не читаем заново
                now=now,
                new_name=new_name,
                dry_run=not REAL_CHANGE,
            )

            # Добавляем статус в результат
            parsed["status"] = "DRY-RUN OK" if not REAL_CHANGE else "Изменено успешно"
            results.append(parsed)

        except Exception as e:
            print(f"  Ошибка: {type(e).__name__}: {e}")
            errors.append((ip, str(e)))

    # Сохраняем отчёт
    if results:
        # Добавляем колонку status в заголовки
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

        with open("ap_rename_report.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()

            for row in results:
                # Добавляем status в словарь
                row_with_status = row.copy()
                row_with_status["status"] = row.get("status", "Не обработано")
                writer.writerow(row_with_status)

        print(f"\nОтчёт сохранён: ap_rename_report.csv ({len(results)} устройств)")

    if errors:
        print("\nОшибки:")
        for ip, err in errors:
            print(f"  {ip}: {err}")

    print("\nГотово.")
