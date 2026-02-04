#!/usr/bin/env python3
import csv
import datetime
import re
import socket
import time
from datetime import datetime

import paramiko


def sendShComm(ip, commands, now, shSleep=0.8, longSleep=4.0, maxRead=32768):
    """
    Подключение к Ruckus Unleashed AP и выполнение списка команд.
    Авторизация внутри shell (логин + пароль вручную).
    """
    USER = "admin"
    PASS = ""  # ← В продакшене спрячь в .env или os.getenv()
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
    now = datetime.now()
    commands = ["get device-name", "get boarddata", "get lldp neighbors"]

    results = []  # сюда собираем все обработанные AP

    # Твой цикл по IP (можно заменить на чтение из файла)
    net = "172.31.99."
    for octet in range(15, 16):
        ip = f"{net}{octet}"
        print(f"\nПроверка {ip}...")

        full_output = sendShComm(ip, commands, now)
        if full_output:
            parsed = parse_and_rename_ap_data(full_output, ip)
            if parsed:
                results.append(parsed)
                print(
                    f"  → {parsed['new_device_name']} (порт {parsed['port'] or 'не найден'})"
                )

    # Сохраняем всё в CSV
    if results:
        save_to_csv(results)
