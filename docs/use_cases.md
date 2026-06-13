# Akita Supermodem Use Cases

Akita Supermodem was built to facilitate reliable, secure, and highly efficient file transfers across environments ranging from high-bandwidth local networks to ultra-low-bandwidth, off-grid mesh networks.

Below are several primary use cases where Akita Supermodem excels.

## 1. Disaster Recovery & Off-Grid Communication
When cellular networks and traditional internet infrastructure fail due to natural disasters (hurricanes, earthquakes) or power grid collapses, communities need a way to share critical information.
* **How it helps**: By leveraging the `meshtastic` profile, emergency responders and citizens can exchange offline maps, medical instructions, or CSV manifests of supplies entirely off-grid.
* **Key Feature**: Robust chunking and resumption mechanisms ensure that even if nodes drop in and out of the mesh, file transfers can eventually complete without restarting from scratch.

## 2. Secure File Drops for Journalists & Activists
In environments with heavy surveillance or censorship, relying on centralized servers (cloud storage, messaging apps) to transfer sensitive files can compromise sources.
* **How it helps**: Akita Supermodem operates purely peer-to-peer over mesh networks or raw LoRa. The integrated **End-to-End Encryption (E2EE)** using X25519 key exchange and ChaCha20-Poly1305 ensures that files are entirely unreadable by intermediate routing nodes.
* **Key Feature**: Perfect forward secrecy and direct node-to-node routing.

## 3. Remote Field Operations & Research
Scientists, surveyors, and military personnel often operate in isolated environments (deep forests, oceans, deserts) where setting up traditional networking is impossible.
* **How it helps**: Sensors and data loggers can be hooked up to a LoRa transceiver. Using the `lora` network profile, accumulated telemetry data or compressed logs can be transmitted back to base camp over distances of several miles.
* **Key Feature**: Dynamic rate-limiting helps avoid flooding the delicate RF spectrum.

## 4. Local High-Speed Peer-to-Peer Sharing
Sometimes you just need to move a massive file (like a video project or a database dump) to a colleague in the same room without uploading it to the internet and downloading it again.
* **How it helps**: Using the `wifi` network profile, Akita Supermodem bypasses its restrictive mesh delays. It dynamically scales up piece sizes to 4KB (or more) and blasts the data across the local LAN or Ad-Hoc WiFi network.
* **Key Feature**: Larger WiFi profile chunks reduce transfer overhead while preserving protocol integrity checks.

## 5. Over-the-Air (OTA) IoT Firmware Updates
Managing fleets of embedded devices or drones requires sending binary firmware payloads reliably over occasionally dropping connections (like Bluetooth or raw radio).
* **How it helps**: Using the `bluetooth` or custom profiles, a central dispatcher can send firmware updates.
* **Key Feature**: The Merkle Tree integrity checks guarantee that the firmware payload hasn't been corrupted in transit before the embedded device attempts to flash it.

## 6. Controlled Peer-To-Peer Distribution
Teams that need repeatable local distribution can standardize on one transfer protocol and one status surface.
* **How it helps**: The CLI and web UI use the same Supermodem packet format, making send, receive, resume, and verification behavior consistent across deployments.
* **Key Feature**: Validated configuration profiles keep packet sizing and timing predictable for each network type.
