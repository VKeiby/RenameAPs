#!/usr/bin/env python3
import csv
import datetime
import re
import socket
import time
from datetime import datetime

import paramiko


def sendShComm(
    ip,
    read_commands,
    now=None,
    new_name=None,
    dry_run=True,
    shSleep=0.8,
    longSleep=4.0,
    maxRead=32768,
):
    """
    Подключается к Ruckus AP, выполняет команды чтения,
    при необходимости меняет имя устройства и применяет конфигурацию.
    """
    USER = "admin"
    PASS = "bsquared2019!@#"
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

            # Чтение текущих данных
            for cmd in read_commands:
                ssh.send(f"{cmd}\n")
                time.sleep(longSleep)
                cmd_out = ""
                timeout = time.time() + 20
                while time.time() < timeout:
                    if ssh.recv_ready():
                        cmd_out += ssh.recv(maxRead).decode("utf-8", errors="replace")
                    time.sleep(0.15)
                    if "rkscli:" in cmd_out.lower():
                        break
                output += f"\n--- {cmd} ---\n{cmd_out.strip()}\n"

            # Изменение имени, если передано
            if new_name:
                print(f"[{ip}] Текущее имя будет изменено на: {new_name}")

                if dry_run:
                    print(f"[{ip}] DRY-RUN: команда не отправлена")
                else:
                    print(f"[{ip}] Отправляю: set device-name {new_name}")
                    ssh.send(f"set device-name {new_name}\n")
                    time.sleep(longSleep)

                    # Читаем ответ на set
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

                    print(f"[{ip}] Ответ на set: {set_out.strip()}")

                    # Применяем изменения
                    print(f"[{ip}] Применяю конфигурацию: apply")
                    ssh.send("apply\n")
                    time.sleep(longSleep * 1.5)

                    apply_out = ""
                    timeout = time.time() + 15
                    while time.time() < timeout:
                        if ssh.recv_ready():
                            apply_out += ssh.recv(maxRead).decode(
                                "utf-8", errors="replace"
                            )
                        time.sleep(0.1)
                        if "rkscli:" in apply_out.lower():
                            break

                    print(f"[{ip}] Ответ на apply: {apply_out.strip()}")

                    # Проверяем новое имя
                    print(f"[{ip}] Проверка нового имени...")
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

                    print(f"[{ip}] Текущее имя после изменений:\n{check_out.strip()}")
                    output += f"\n--- Изменение имени ---\n{check_out.strip()}\n"

            # Сохраняем лог
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
    now = datetime.now()
    read_commands = ["get device-name", "get boarddata", "get lldp neighbors"]

    # Тест на одной точке
    test_ip = "172.31.99.15"
    print(f"\n=== Тест на {test_ip} ===")

    full_output = sendShComm(test_ip, read_commands, now=None)  # first read only
    if full_output:
        parsed = parse_and_rename_ap_data(full_output, test_ip)
        if parsed and parsed["port"]:
            new_name = parsed["new_device_name"]
            print(f"Предлагаемое имя: {new_name}")

            # 1. Dry-run
            # print("\nСначала dry-run:")
            # sendShComm(test_ip, [], new_name=new_name, dry_run=True)

            # 2. Реальное изменение — раскомментировать только после успешного dry-run!
            print("\nРеальное изменение:")
            sendShComm(test_ip, [], new_name=new_name, dry_run=False)
