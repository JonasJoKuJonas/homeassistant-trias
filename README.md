# 🚌 Trias Integration for Home Assistant

[![HACS Badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/github/v/release/JonasJoKuJonas/homeassistant-trias?style=flat&label=Latest%20Version)](https://github.com/JonasJoKuJonas/homeassistant-trias/releases)
[![Downloads](https://img.shields.io/github/downloads/JonasJoKuJonas/homeassistant-trias/total?style=flat&label=Total%20Downloads)](https://tooomm.github.io/github-release-stats/?username=JonasJoKuJonas&repository=HomeAssistant-trias)
[![HACS Installations](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=HACS%20Installations&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.trias.total)](https://github.com/JonasJoKuJonas/homeassistant-trias)
[![Latest Release Date](https://img.shields.io/github/release-date/JonasJoKuJonas/homeassistant-trias?style=flat&label=Latest%20Release)](https://github.com/JonasJoKuJonas/homeassistant-trias/releases)
[![Open Issues](https://img.shields.io/github/issues/JonasJoKuJonas/homeassistant-trias?style=flat&label=Open%20Issues)](https://github.com/JonasJoKuJonas/homeassistant-trias/issues)

---

## 📖 Overview

**Trias** is a custom integration for Home Assistant that connects to the [Trias API](https://www.vdv.de/trias.aspx)

With this integration, you can:

- **Display real-time departure times** for buses, trams, and trains at specific stations
- **Plan journeys** between stops and get accurate arrival forecasts
- **Monitor public transport** directly from your Home Assistant dashboard

---

## 🌍 Supported Providers

This integration supports multiple Trias-compliant public transport providers. For a list, visit the [Trias Providers Documentation](https://github.com/andaryjo/trias-client/blob/main/docs/PROVIDERS.md).

---

## 📥 Installation

### Option 1: HACS (Recommended)

This integration is available in the default HACS repository. Install it with just a few clicks:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JonasJoKuJonas&repository=homeassistant-trias&category=integration)

**Manual HACS installation:**

1. Go to **HACS** → **Integrations** in your Home Assistant sidebar
2. Click **Explore & Add Repositories**
3. Search for `trias`
4. Click **Install**
5. Restart Home Assistant

---

### Option 2: Manual Installation

<details>
<summary>Click to expand manual installation steps</summary>

1. Download the latest release from the [releases page](https://github.com/JonasJoKuJonas/homeassistant-trias/releases)
2. Extract the ZIP file
3. Copy the `custom_components/trias/` folder to your Home Assistant `custom_components/` directory
4. Restart Home Assistant

</details>

---

## ⚙️ Configuration

After installation, set up the integration through the Home Assistant UI:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=trias)

**Step-by-step:**

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration** in the bottom right
3. Search for `trias` and select it
4. Enter your **API key** and **endpoint URL** for your Trias provider
5. Click **Submit** to complete the initial setup

### 🔧 Options Flow (Adding Sensors)

After the initial setup, configure your sensors through the options flow:

1. Find the `trias` integration in **Devices & Services**
2. Click **Configure** (the gear icon) on the `trias` entry
3. In the options flow, you can add:
   - **📍 Stations**: Add stop/station sensors for departure monitoring
   - **🗺️ Trips**: Add journey/trip sensors for route planning between stops
4. Follow the prompts to select your desired stops, stations, or routes
5. Click **Submit** to create the sensors

---

## 🚀 Usage Examples

### Display Departure Boards

This integration works perfectly with the [Departure Card](https://github.com/BagelBeef/ha-departureCard) – a custom Lovelace card designed specifically for displaying public transport departures.

**Example configuration:**

```yaml
type: custom:departure-card
entity: sensor.<sensor_id>
connections_attribute: departures
fontSize: xl
convertTimeHHMM: true
train: LineName
delay: DelayMinutes
platform: PlannedBay
departure: StartTime
title: "Departures"
```
