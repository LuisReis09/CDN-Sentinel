from __future__ import annotations

import argparse
import signal
import time


def main() -> None:
    parser = argparse.ArgumentParser(description="Processo independente de um cliente simulado")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--city", default="unknown")
    args = parser.parse_args()

    running = True

    def stop(*_args: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop)

    # O processo representa o runtime do player/cliente. O control plane continua
    # orquestrando streams via HTTP para manter a simulação observável em um só lugar.
    while running:
        time.sleep(0.5)


if __name__ == "__main__":
    main()
