import csv
import re
import time
from datetime import datetime

import paramiko


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
    username=None,
    password=None,
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
            username=username,
            password=password,
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

            ssh.send(f"{username}\n")
            time.sleep(shSleep)
            ssh.send(f"{password}\n")
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
    parsing_boarddata = False

    for line in lines:
        line_clean = line.strip()

        # ─── get device-name ───
        if line_clean.startswith("device name :"):
            m = re.search(r"device name\s*:\s*['\"]?([^'\"]+)['\"]?", line_clean, re.I)
            if m:
                data["original_device_name"] = m.group(1).strip()

        # ─── начало блока get boarddata ───
        if line_clean.startswith("get boarddata"):
            parsing_boarddata = True
            continue

        if parsing_boarddata:
            # Ищем строку с базовым MAC
            if "MAC Address Pool" in line_clean and "base" in line_clean.lower():
                mac_match = re.search(r"base\s*(?::\s*)?([0-9A-Fa-f:]{17})", line, re.I)
                if mac_match:
                    data["base_mac"] = mac_match.group(1).strip()

            # Модель и серийник
            if line_clean.startswith("name:"):
                data["model"] = line_clean.split(":", 1)[1].strip()
            if "Serial#:" in line_clean:
                data["serial"] = line_clean.split(":", 1)[1].strip()

        # ─── get lldp neighbors ─── порт из коммутатора
        if "PortDescr:" in line_clean:
            # Более надёжное выражение, ищет последнюю цифру/цифры после /
            m = re.search(r"PortDescr:\s*.*\/(\d+)", line_clean, re.I)
            if m:
                data["port"] = m.group(1).zfill(2)  # 01, 02, ..., 17

    # ─── Логика формирования имени ───
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
        data["status"] = "Порт или имя не определены"

    return data


# ────────────────────────────────────────────────
# Сохранение отчёта
# ────────────────────────────────────────────────
def save_to_csv(results: list[dict], filename="range_report.csv"):
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
def process_single_ip(ip, read_commands, now, REAL_CHANGE, username, password):
    try:
        full_output = sendShComm(
            ip,
            read_commands,
            now=now,
            new_name=None,
            dry_run=True,
            username=username,
            password=password,
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

        sendShComm(
            ip,
            [],
            now=now,
            new_name=new_name,
            dry_run=not REAL_CHANGE,
            username=username,
            password=password,
        )

        parsed["status"] += " (изменено)" if REAL_CHANGE else " (dry-run)"
        return parsed, None

    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
