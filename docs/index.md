# Akita Supermodem Documentation

Welcome to the documentation for Akita Supermodem.

## Overview

Akita Supermodem provides a robust file transfer mechanism suitable for low-bandwidth mesh networks like Meshtastic. It handles file segmentation, integrity checking, and retransmission of lost data.

## Key Components

* **Protocol:** Defines the messages exchanged between sender and receiver. See [Protocol Details](protocol.md).
* **Sender (`AkitaSender`):** Class responsible for initiating transfers and sending file pieces.
* **Receiver (`AkitaReceiver`):** Class responsible for receiving pieces, managing state, requesting missing data, and assembling the final file.
* **Meshtastic Integration:** Relies on a Meshtastic interface object (`meshtastic.SerialInterface` or similar) for network communication.

## Getting Started

1.  **Installation:** Follow the instructions in the main [README.md](../README.md). Ensure you have `protoc` installed and generate the necessary Python code from `akita.proto`.
2.  **Usage:** See the [Usage Guide](usage.md) for examples on how to integrate the sender and receiver into your Meshtastic application.

## Contents

* [Protocol Details](protocol.md)
* [Usage Guide](usage.md)
* [Examples](../examples/)

