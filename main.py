# main.py
from fatigue_framework import FatigueMonitor
import datetime
import psutil, os, threading
import csv

# ── MEDIDOR DE MÉTRICAS DE HARDWARE ──────────────────────────────
proceso = psutil.Process(os.getpid())
muestras_cpu, muestras_ram, midiendo = [], [], True
tiempo_inicio = datetime.datetime.now()

def _medir():
    while midiendo:
        muestras_cpu.append(psutil.cpu_percent(interval=1))
        muestras_ram.append(proceso.memory_info().rss / 1024 / 1024)

threading.Thread(target=_medir, daemon=True).start()
# ─────────────────────────────────────────────────────────────────

def registrar_parpadeo(total_parpadeos):
    hora_actual = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] Parpadeo detectado. Total: {total_parpadeos}")

def registrar_bostezo(total_bostezos):
    hora_actual = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{hora_actual}] ¡ALERTA! Bostezo detectado. Total: {total_bostezos}")

# Configuración del monitor
# Umbrales relativos al perfil del sujeto (calibración automática al iniciar; tecla C para recalibrar)
monitor = FatigueMonitor(video_source=0)

# Conexión de callbacks
monitor.on_blink(registrar_parpadeo)
monitor.on_yawn(registrar_bostezo)

if __name__ == "__main__":
    monitor.start()

    # ── RESUMEN Y EXPORTACIÓN AL CERRAR ─────────────────────────────
    midiendo = False
    tiempo_fin = datetime.datetime.now()
    duracion_segundos = int((tiempo_fin - tiempo_inicio).total_seconds())
    
    cpu_prom = sum(muestras_cpu) / len(muestras_cpu) if muestras_cpu else 0.0
    ram_prom = sum(muestras_ram) / len(muestras_ram) if muestras_ram else 0.0

    print("\n" + "="*45)
    print("RESUMEN DE LA SESIÓN")
    print(f"Duración: {duracion_segundos} segundos")
    print(f"Parpadeos detectados: {monitor.blink_count}")
    print(f"Bostezos detectados:  {monitor.yawn_count}")
    print(f"CPU promedio:         {cpu_prom:.1f}%")
    print(f"RAM promedio:         {ram_prom:.1f} MB")
    print("="*45)

    archivo_csv = "resultados_experimento.csv"
    existe_archivo = os.path.exists(archivo_csv)

    with open(archivo_csv, mode='a', newline='') as f:
        writer = csv.writer(f)
        if not existe_archivo:
            writer.writerow(["Fecha_Hora", "Duracion_Seg", "Parpadeos", "Bostezos", "CPU_Promedio", "RAM_MB"])
        writer.writerow([
            tiempo_inicio.strftime("%Y-%m-%d %H:%M:%S"),
            duracion_segundos,
            monitor.blink_count,
            monitor.yawn_count,
            f"{cpu_prom:.1f}",
            f"{ram_prom:.1f}"
        ])
        
    print(f"\nDatos guardados exitosamente en '{archivo_csv}'.")