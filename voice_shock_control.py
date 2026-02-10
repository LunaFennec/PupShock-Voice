import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import sounddevice as sd
import numpy as np
import requests
import queue
import time
import re
import threading
import json
import os
from vosk import Model, KaldiRecognizer
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw
import sys
import webbrowser
import zipfile
import urllib.request
from word2number import w2n

# App version
VERSION = "1.0.0"
GITHUB_REPO = "LunaFennec/PupShock-Voice"

# Vosk model configurations
VOSK_MODELS = {
    "small": {
        "name": "vosk-model-small-en-us-0.15",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "size": "40 MB"
    },
    "large": {
        "name": "vosk-model-en-us-0.22",
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip",
        "size": "1.8 GB"
    }
}

class VoiceShockApp:
    def __init__(self):
        # Init main window
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("dark-blue")
        
        self.root = ctk.CTk()
        self.root.title("PupShock Voice")
        self.root.geometry("900x750")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Set window icon
        self.set_window_icon()
        
        # Load config
        self.config_file = "config.json"
        self.load_config()
        
        # Variables
        self.running = False
        self.model = None
        self.recognizer = None
        self.stream = None
        self.loopback_stream = None
        self.audio_queue = queue.Queue()
        
        # Runtime state
        self.last_action_time = 0
        self.last_command_text = ""
        self.silence_start = None
        self.has_speech = False
        self.last_speech_time = None
        
        # Audio level for VU meter
        self.current_audio_level = 0
        
        # Tray icon
        self.tray_icon = None
        
        # Update check flag
        self.update_available = False
        self.latest_version = None
        self.download_url = None
        
        # Build UI
        self.create_ui()
        
        # Start VU meter
        self.update_vu_meter()
        
        # Check for updates in background
        self.check_for_updates()
        
    def load_config(self):
        # Load default config and override with file if exists
        default_config = {
            "api_token": "",
            "control_id": "",
            "wake_word": "lightning bolt",
            "audio_device": 0,
            "max_intensity": 100,
            "duration_ms": 1000,
            "cooldown_seconds": 10,
            "sample_rate": 16000,
            "chunk_size": 512,
            "silence_threshold": 0.01,
            "silence_duration": 0.5,
            "state_reset_timeout": 5.0,
            "model_size": "small",
            "loopback_enabled": False,
            "loopback_device": 0,
            "loopback_mix_ratio": 0.5
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    loaded_config = json.load(f)
                    default_config.update(loaded_config)
            except Exception as e:
                print(f"Error loading config: {e}")
        
        self.config = default_config
        
    def save_config(self):
        # Save current config to file
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            self.log_message("Configuration saved")
        except Exception as e:
            self.log_message(f"Error saving config: {e}", level="ERROR")
    
    def check_for_updates(self):
        # Check for updates thru github
        def check():
            try:
                # Ping GitHub API for latest release
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                response = requests.get(url, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    latest_version = data.get('tag_name', '').lstrip('v')
                    
                    if self.is_newer_version(latest_version, VERSION):
                        self.update_available = True
                        self.latest_version = latest_version
                        self.download_url = data.get('html_url', f"https://github.com/{GITHUB_REPO}/releases/latest")
                        
                        # Schedule UI update on main thread
                        self.root.after(0, self.show_update_notification)
                        self.log_message(f"Update available: v{latest_version}")
                    else:
                        self.log_message(f"You are running the latest version (v{VERSION})")
                elif response.status_code == 404:
                    # No releases found
                    self.log_message("No releases found on GitHub")
                else:
                    self.log_message(f"Failed to check for updates: HTTP {response.status_code}", level="WARNING")
                    
            except requests.exceptions.RequestException as e:
                # Network error - fail silently
                self.log_message(f"Could not check for updates: {e}", level="WARNING")
            except Exception as e:
                self.log_message(f"Update check error: {e}", level="WARNING")
        
        # Run in background thread
        update_thread = threading.Thread(target=check, daemon=True)
        update_thread.start()
    
    def is_newer_version(self, latest, current):
        # Compare versions
        try:
            latest_parts = [int(x) for x in latest.split('.')]
            current_parts = [int(x) for x in current.split('.')]
            
            # Pad to same length
            while len(latest_parts) < len(current_parts):
                latest_parts.append(0)
            while len(current_parts) < len(latest_parts):
                current_parts.append(0)
            
            return latest_parts > current_parts
        except:
            return False
    
    def show_update_notification(self):
        # Show update notif dialog
        response = messagebox.askquestion(
            "Update Available",
            f"A new version is available!\n\n"
            f"Current version: v{VERSION}\n"
            f"Latest version: v{self.latest_version}\n\n"
            f"Would you like to download the update?",
            icon='info'
        )
        
        if response == 'yes' and self.download_url:
            webbrowser.open(self.download_url)
    
    def get_model_path(self):
        # Get path to vosk model based on config
        model_info = VOSK_MODELS.get(self.config["model_size"], VOSK_MODELS["small"])
        model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", model_info["name"])
        return model_dir
    
    def download_model(self, model_size):
        # Download model if not present
        model_info = VOSK_MODELS.get(model_size, VOSK_MODELS["small"])
        model_dir = self.get_model_path()
        
        if os.path.exists(model_dir):
            self.log_message(f"Model already downloaded: {model_info['name']}")
            return True
        
        self.log_message(f"Downloading model: {model_info['name']} ({model_info['size']})")
        self.log_message("This may take a while on first run...")
        
        try:
            # Create models directory
            os.makedirs(os.path.dirname(model_dir), exist_ok=True)
            
            # Download zip file
            zip_path = model_dir + ".zip"
            self.log_message("Downloading...")
            urllib.request.urlretrieve(model_info["url"], zip_path)
            
            # Extract
            self.log_message("Extracting model...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(os.path.dirname(model_dir))
            
            # Clean up zip
            os.remove(zip_path)
            
            self.log_message("Model download complete!")
            return True
            
        except Exception as e:
            self.log_message(f"Failed to download model: {e}", level="ERROR")
            return False
            
    def create_ui(self):
        # Create main UI
        # Create notebook
        self.notebook = ctk.CTkTabview(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Add tabs
        self.notebook.add("Console")
        self.notebook.add("Audio")
        self.notebook.add("Settings")
        self.notebook.add("API")
        
        # Create tab contents
        self.create_console_tab()
        self.create_audio_tab()
        self.create_settings_tab()
        self.create_api_tab()
        
        # Add control buttons
        self.create_control_panel()
        
    def create_console_tab(self):
        # Create console tab
        tab = self.notebook.tab("Console")
        
        # Add console output
        console_frame = ctk.CTkFrame(tab)
        console_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(console_frame, text="Console Output", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=5)
        
        # Add text widget with scrollbar
        text_frame = ctk.CTkFrame(console_frame)
        text_frame.pack(fill="both", expand=True, pady=5)
        
        self.console_text = tk.Text(text_frame, wrap=tk.WORD, 
                                   bg="#2b2b2b", fg="#ffffff",
                                   font=("Consolas", 10))
        scrollbar = ctk.CTkScrollbar(text_frame, command=self.console_text.yview)
        self.console_text.configure(yscrollcommand=scrollbar.set)
        
        self.console_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Add clear button
        ctk.CTkButton(console_frame, text="Clear Console", 
                     command=self.clear_console).pack(pady=5)
        
    def create_audio_tab(self):
        # Create audio settings tab
        tab = self.notebook.tab("Audio")
        
        # Microphone device selection
        device_frame = ctk.CTkFrame(tab)
        device_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(device_frame, text="Microphone Input Device", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=5)
        
        # Get audio devices
        self.audio_devices = []
        host_apis = sd.query_hostapis()
        
        # Find MME host API index
        mme_index = None
        for i, api in enumerate(host_apis):
            if 'MME' in api['name']:
                mme_index = i
                break
        
        for i, device in enumerate(sd.query_devices()):
            if device["max_input_channels"] > 0:
                # Filter to just MME devices, or all if none found
                if mme_index is None or device['hostapi'] == mme_index:
                    self.audio_devices.append(f"{i}: {device['name']}")
        
        self.device_var = ctk.StringVar(value=self.audio_devices[self.config["audio_device"]] 
                                        if self.config["audio_device"] < len(self.audio_devices) 
                                        else self.audio_devices[0])
        
        device_menu = ctk.CTkOptionMenu(device_frame, variable=self.device_var,
                                       values=self.audio_devices,
                                       command=self.on_device_change)
        device_menu.pack(pady=10, padx=20, fill="x")
        
        # System audio device selection
        loopback_frame = ctk.CTkFrame(tab)
        loopback_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(loopback_frame, text="System Audio", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=5)
        
        # Enable loopback checkbox
        self.loopback_enabled_var = ctk.BooleanVar(value=self.config["loopback_enabled"])
        ctk.CTkCheckBox(loopback_frame, text="Enable System Audio", 
                       variable=self.loopback_enabled_var,
                       command=self.on_loopback_toggle).pack(pady=5)
        
        # Get loopback devices
        self.loopback_devices = []
        
        # Find WASAPI host API index
        wasapi_index = None
        for i, api in enumerate(host_apis):
            if 'WASAPI' in api['name']:
                wasapi_index = i
                break
        
        # Look for MME loopback devices
        for i, device in enumerate(sd.query_devices()):
            device_name = device['name'].lower()
            if device["max_input_channels"] > 0 and any(keyword in device_name for keyword in 
                ['stereo mix', 'wave out', 'loopback', 'what u hear', 'what you hear', 'wave out mix']):
                self.loopback_devices.append(f"{i}: {device['name']} (MME Loopback)")
        
        # Add WASAPI output devices
        if wasapi_index is not None:
            for i, device in enumerate(sd.query_devices()):
                if device["max_output_channels"] > 0 and device['hostapi'] == wasapi_index:
                    self.loopback_devices.append(f"{i}: {device['name']} (WASAPI)")
        
        # If no devices found list everything
        if not self.loopback_devices:
            for i, device in enumerate(sd.query_devices()):
                if device["max_input_channels"] > 0:
                    if mme_index is None or device['hostapi'] == mme_index:
                        self.loopback_devices.append(f"{i}: {device['name']} (MME)")
        
        # Fallback message if nothing found
        if not self.loopback_devices:
            self.loopback_devices = ["0: No devices found - Check audio settings"]
        
        self.loopback_device_var = ctk.StringVar(value=self.loopback_devices[0])
        if self.config["loopback_device"] < len(self.loopback_devices):
            self.loopback_device_var.set(self.loopback_devices[self.config["loopback_device"]])
        
        self.loopback_menu = ctk.CTkOptionMenu(loopback_frame, variable=self.loopback_device_var,
                                              values=self.loopback_devices,
                                              command=self.on_loopback_device_change)
        self.loopback_menu.pack(pady=10, padx=20, fill="x")
        
        # Mix ratio slider
        mix_frame = ctk.CTkFrame(loopback_frame)
        mix_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(mix_frame, text="Audio Mix:", width=80).pack(side="left", padx=5)
        ctk.CTkLabel(mix_frame, text="Mic", width=30).pack(side="left", padx=2)
        
        self.mix_ratio_slider = ctk.CTkSlider(mix_frame, from_=0, to=1, 
                                             number_of_steps=20)
        self.mix_ratio_slider.set(self.config["loopback_mix_ratio"])
        self.mix_ratio_slider.pack(side="left", fill="x", expand=True, padx=5)
        
        ctk.CTkLabel(mix_frame, text="Speaker", width=50).pack(side="left", padx=2)
        
        self.mix_value_label = ctk.CTkLabel(mix_frame, text=f"{int(self.config['loopback_mix_ratio']*100)}%", width=40)
        self.mix_value_label.pack(side="left", padx=5)
        
        def update_mix_label(val):
            self.mix_value_label.configure(text=f"{int(float(val)*100)}%")
        
        self.mix_ratio_slider.configure(command=update_mix_label)
        
        # Info label
        info_label = ctk.CTkLabel(loopback_frame, 
                                 text="Loopback System Audio - Requires stereo mix or WASAPI loopback device.\n If none are found, try enabling 'Stereo Mix' in Windows Sound settings.",
                                 font=ctk.CTkFont(size=10),
                                 text_color="gray",
                                 wraplength=550)
        info_label.pack(pady=5)
        
        # VU Meter
        vu_frame = ctk.CTkFrame(tab)
        vu_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(vu_frame, text="Audio Level Monitor", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=5)
        
        self.vu_canvas = tk.Canvas(vu_frame, height=100, bg="#2b2b2b", 
                                  highlightthickness=0)
        self.vu_canvas.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Status label
        self.status_label = ctk.CTkLabel(vu_frame, text="Status: Stopped", 
                                        font=ctk.CTkFont(size=14))
        self.status_label.pack(pady=5)
        
    def create_settings_tab(self):
        # Create settings tab
        tab = self.notebook.tab("Settings")
        
        # Scrollable frame
        scroll_frame = ctk.CTkScrollableFrame(tab)
        scroll_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Version info at top
        version_frame = ctk.CTkFrame(scroll_frame)
        version_frame.pack(fill="x", pady=10, padx=5)
        
        version_label = ctk.CTkLabel(version_frame, 
                                     text=f"PupShock Voice v{VERSION}",
                                     font=ctk.CTkFont(size=14, weight="bold"))
        version_label.pack(side="left", padx=10)
        
        if self.update_available:
            update_btn = ctk.CTkButton(version_frame, 
                                      text=f"Update Available (v{self.latest_version})",
                                      command=lambda: webbrowser.open(self.download_url) if self.download_url else None,
                                      fg_color="green",
                                      hover_color="darkgreen",
                                      width=200)
            update_btn.pack(side="right", padx=10)
        else:
            check_update_btn = ctk.CTkButton(version_frame,
                                            text="Check for Updates",
                                            command=self.check_for_updates,
                                            width=150)
            check_update_btn.pack(side="right", padx=10)
        
        # Wake word box
        wake_frame = ctk.CTkFrame(scroll_frame)
        wake_frame.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(wake_frame, text="Wake Word:").pack(side="left", padx=5)
        self.wake_word_var = ctk.StringVar(value=self.config["wake_word"])
        ctk.CTkEntry(wake_frame, textvariable=self.wake_word_var, 
                    width=200).pack(side="left", padx=5)
        
        # Model Size selection
        model_frame = ctk.CTkFrame(scroll_frame)
        model_frame.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(model_frame, text="Model Size:").pack(side="left", padx=5)
        self.model_var = ctk.StringVar(value=self.config["model_size"])
        ctk.CTkOptionMenu(model_frame, variable=self.model_var,
                         values=["small", "large"]).pack(side="left", padx=5)
        
        # Model info label
        model_info = ctk.CTkLabel(model_frame, 
                                 text="(small=40MB, fast / large=1.8GB, accurate)",
                                 font=ctk.CTkFont(size=10),
                                 text_color="gray")
        model_info.pack(side="left", padx=10)
        
        # Create sliders for numeric settings
        self.create_slider(scroll_frame, "Max Intensity (%)", "max_intensity", 0, 100, 1)
        self.create_slider(scroll_frame, "Duration (ms)", "duration_ms", 100, 5000, 100)
        self.create_slider(scroll_frame, "Cooldown (sec)", "cooldown_seconds", 1, 60, 1)
        self.create_slider(scroll_frame, "Silence Threshold", "silence_threshold", 
                          0.001, 0.1, 0.001)
        self.create_slider(scroll_frame, "Silence Duration (sec)", "silence_duration", 
                          0.1, 2.0, 0.1)
        
        # Save button
        ctk.CTkButton(scroll_frame, text="Save Settings", 
                     command=self.save_settings).pack(pady=20)
        
    def create_slider(self, parent, label, config_key, min_val, max_val, step):
        # Helper for labelled slider
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=5, padx=5)
        
        label_widget = ctk.CTkLabel(frame, text=f"{label}:")
        label_widget.pack(side="left", padx=5)
        
        value_label = ctk.CTkLabel(frame, text=f"{self.config[config_key]:.3f}")
        value_label.pack(side="right", padx=5)
        
        slider = ctk.CTkSlider(frame, from_=min_val, to=max_val, 
                              number_of_steps=int((max_val - min_val) / step))
        slider.set(self.config[config_key])
        slider.pack(side="left", fill="x", expand=True, padx=5)
        
        def update_label(val):
            value_label.configure(text=f"{float(val):.3f}")
        
        slider.configure(command=update_label)
        
        # Store reference
        setattr(self, f"{config_key}_slider", slider)
        
    def create_api_tab(self):
        # Create API config tab
        tab = self.notebook.tab("API")
        
        frame = ctk.CTkFrame(tab)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(frame, text="OpenShock API Configuration", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        
        # API Token box
        token_frame = ctk.CTkFrame(frame)
        token_frame.pack(fill="x", pady=10, padx=20)
        ctk.CTkLabel(token_frame, text="API Token:", width=100).pack(side="left", padx=5)
        self.api_token_var = ctk.StringVar(value=self.config["api_token"])
        ctk.CTkEntry(token_frame, textvariable=self.api_token_var, 
                    show="*", width=400).pack(side="left", fill="x", expand=True, padx=5)
        
        # Control ID box
        control_frame = ctk.CTkFrame(frame)
        control_frame.pack(fill="x", pady=10, padx=20)
        ctk.CTkLabel(control_frame, text="Control ID:", width=100).pack(side="left", padx=5)
        self.control_id_var = ctk.StringVar(value=self.config["control_id"])
        ctk.CTkEntry(control_frame, textvariable=self.control_id_var, 
                    width=400).pack(side="left", fill="x", expand=True, padx=5)
        
        # Button frame for test and save
        button_frame = ctk.CTkFrame(frame)
        button_frame.pack(pady=20)
        
        ctk.CTkButton(button_frame, text="Save API Settings", 
                     command=self.save_api_settings,
                     width=200).pack(side="left", padx=5)
        
        ctk.CTkButton(button_frame, text="Test Connection (10% shock)", 
                     command=self.test_api,
                     width=200).pack(side="left", padx=5)
        
    def create_control_panel(self):
        # Create control buttons at the bottom
        control_frame = ctk.CTkFrame(self.root)
        control_frame.pack(fill="x", padx=10, pady=10)
        
        self.start_button = ctk.CTkButton(control_frame, text="Start Listening :3", 
                                         command=self.toggle_listening,
                                         font=ctk.CTkFont(size=14, weight="bold"),
                                         height=40)
        self.start_button.pack(side="left", padx=5, fill="x", expand=True)
        
        ctk.CTkButton(control_frame, text="Minimize to Tray", 
                     command=self.minimize_to_tray,
                     height=40).pack(side="left", padx=5)
        
    def on_device_change(self, selection):
        # Handle audio device change
        device_index = int(selection.split(":")[0])
        self.config["audio_device"] = device_index
        self.log_message(f"Audio device changed to: {selection}")
        
    def on_loopback_toggle(self):
        # Handle loopback enable/disable
        self.config["loopback_enabled"] = self.loopback_enabled_var.get()
        status = "enabled" if self.config["loopback_enabled"] else "disabled"
        self.log_message(f"Speaker loopback {status}")
        
    def on_loopback_device_change(self, selection):
        # Handle loopback device change
        device_index = int(selection.split(":")[0])
        self.config["loopback_device"] = device_index
        self.log_message(f"Loopback device changed to: {selection}")
        
    def save_settings(self):
        # Save all settings
        self.config["wake_word"] = self.wake_word_var.get()
        self.config["model_size"] = self.model_var.get()
        self.config["api_token"] = self.api_token_var.get()
        self.config["control_id"] = self.control_id_var.get()
        self.config["loopback_enabled"] = self.loopback_enabled_var.get()
        self.config["loopback_mix_ratio"] = self.mix_ratio_slider.get()
        
        # Get slider values
        slider_keys = ["max_intensity", "duration_ms", "cooldown_seconds", 
                      "silence_threshold", "silence_duration"]
        
        for key in slider_keys:
            slider = getattr(self, f"{key}_slider")
            self.config[key] = slider.get()
        
        self.save_config()
        
    def save_api_settings(self):
        # Save API settings only
        self.config["api_token"] = self.api_token_var.get()
        self.config["control_id"] = self.control_id_var.get()
        self.save_config()
        
    def log_message(self, message: str, level: str ="INFO") -> None:
        # Add msg to console
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] [{level}] {message}\n"
        
        self.console_text.insert(tk.END, formatted)
        self.console_text.see(tk.END)
        
        # Also print to standard output
        print(formatted.strip())
        
    def clear_console(self):
        # Clear console
        self.console_text.delete(1.0, tk.END)
        
    def update_vu_meter(self):
        # Update VU meter display
        if self.vu_canvas.winfo_exists():
            width = self.vu_canvas.winfo_width()
            height = self.vu_canvas.winfo_height()
            
            if width > 1 and height > 1:
                self.vu_canvas.delete("all")
                
                # Draw background
                self.vu_canvas.create_rectangle(0, 0, width, height, 
                                               fill="#2b2b2b", outline="")
                
                # Draw level bar
                level_width = int(width * self.current_audio_level)
                
                # Color gradient based on level
                if self.current_audio_level < 0.3:
                    color = "#00ff00"  # Green
                elif self.current_audio_level < 0.7:
                    color = "#ffff00"  # Yellow
                else:
                    color = "#ff0000"  # Red
                
                if level_width > 0:
                    self.vu_canvas.create_rectangle(0, 0, level_width, height, 
                                                   fill=color, outline="")
                
                # Draw markers
                for i in range(0, 11):
                    x = int(width * i / 10)
                    self.vu_canvas.create_line(x, 0, x, height, 
                                              fill="#555555", width=1)
        
        self.root.after(50, self.update_vu_meter)
        
    def toggle_listening(self):
        # Start/stop listening
        if not self.running:
            self.start_listening()
        else:
            self.stop_listening()
            
    def start_listening(self):
        # Start audio processing
        if not self.config["api_token"] or not self.config["control_id"]:
            self.log_message("Please configure API token and Control ID first!", level="ERROR")
            self.notebook.set("API")
            return
        
        self.running = True
        self.start_button.configure(text="Stop Listening")
        self.status_label.configure(text="Status: Loading model...")
        self.log_message("Starting voice control...")
        
        # Start processing thread
        thread = threading.Thread(target=self.processing_thread, daemon=True)
        thread.start()
        
    def stop_listening(self):
        # Stop audio processing
        self.running = False
        self.start_button.configure(text="Start Listening :3")
        self.status_label.configure(text="Status: Stopped")
        
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        
        if self.loopback_stream:
            self.loopback_stream.stop()
            self.loopback_stream.close()
            self.loopback_stream = None
        
        self.log_message("Stopped listening")
        
    def processing_thread(self):
        # Main audio processing thread
        try:
            # Download model if needed
            if not self.download_model(self.config["model_size"]):
                self.log_message("Failed to download model, cannot start", level="ERROR")
                self.root.after(0, self.stop_listening)
                return
            
            # Load model
            self.log_message(f"Loading {self.config['model_size']} model...")
            model_path = self.get_model_path()
            self.model = Model(model_path)
            
            # Create recognizer with 16kHz sample rate
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.recognizer.SetWords(True)
            
            self.log_message("Model loaded successfully")
            
            # Get device info
            device_index = self.config["audio_device"]
            device_info = sd.query_devices(device_index, 'input')
            native_rate = int(device_info['default_samplerate'])
            self.log_message(f"Using device: {device_info['name']}")
            self.log_message(f"Native sample rate: {native_rate} Hz")
            
            # Start audio stream
            self.stream = sd.InputStream(
                samplerate=native_rate,
                channels=1,
                dtype="float32",
                blocksize=self.config["chunk_size"],
                device=device_index,
                callback=self.audio_callback
            )
            self.stream.start()
            
            # Start system audio stream if enabled
            if self.config["loopback_enabled"]:
                try:
                    loopback_index = self.config["loopback_device"]
                    loopback_info = sd.query_devices(loopback_index)
                    
                    # Check if a WASAPI output device is being used for loopback
                    is_wasapi_output = (loopback_info["max_output_channels"] > 0 and 
                                       loopback_info["max_input_channels"] == 0)
                    
                    if is_wasapi_output:
                        # Open output device as input
                        self.log_message("Using WASAPI loopback mode")
                        loopback_rate = int(loopback_info['default_samplerate'])
                        
                        
                        self.loopback_stream = sd.InputStream(
                            samplerate=loopback_rate,
                            channels=1,
                            dtype="float32",
                            blocksize=self.config["chunk_size"],
                            device=loopback_index,
                            callback=self.loopback_audio_callback
                        )
                    else:
                        # Regular input device
                        loopback_rate = int(loopback_info['default_samplerate'])
                        
                        self.loopback_stream = sd.InputStream(
                            samplerate=loopback_rate,
                            channels=1,
                            dtype="float32",
                            blocksize=self.config["chunk_size"],
                            device=loopback_index,
                            callback=self.loopback_audio_callback
                        )
                    
                    self.loopback_stream.start()
                    self.log_message(f"Loopback device: {loopback_info['name']}")
                    self.log_message(f"Mix ratio: {int(self.config['loopback_mix_ratio']*100)}% speaker")
                except Exception as e:
                    self.log_message(f"Failed to start loopback: {e}", level="WARNING")
                    self.log_message("Try a different loopback device or check Windows audio settings", level="WARNING")
                    self.log_message("Continuing with microphone only", level="WARNING")
            
            self.status_label.configure(text="Status: Listening...")
            self.log_message(f"Listening for wake word: '{self.config['wake_word']}'")
            
            # Main processing loop
            while self.running:
                try:
                    chunk = self.audio_queue.get(timeout=0.1)
                    self.process_audio_chunk(chunk, native_rate)
                except queue.Empty:
                    continue
                    
        except Exception as e:
            self.log_message(f"Error in processing thread: {e}", level="ERROR")
            self.root.after(0, self.stop_listening)
            
    def audio_callback(self, indata, frames, time_info, status):
        # Audio input callback
        if status:
            self.log_message(f"Audio status: {status}", level="WARNING")
        
        audio_data = indata[:, 0].copy()
        
        # If loopback is enabled, apply mic mix ratio
        if self.config["loopback_enabled"]:
            mic_ratio = 1.0 - self.config["loopback_mix_ratio"]
            audio_data = audio_data * mic_ratio
        
        self.audio_queue.put(audio_data)
        
        # Update VU meter
        rms = np.sqrt(np.mean(audio_data ** 2))
        self.current_audio_level = min(1.0, rms * 10)  # Scale for visibility
        
    def loopback_audio_callback(self, indata, frames, time_info, status):
        # Loopback audio callback
        if status:
            self.log_message(f"Loopback status: {status}", level="WARNING")
        
        loopback_data = indata[:, 0].copy()
        
        # Apply speaker mix ratio
        speaker_ratio = self.config["loopback_mix_ratio"]
        loopback_data = loopback_data * speaker_ratio
        
        # Add to queue
        self.audio_queue.put(loopback_data)
        
    def process_audio_chunk(self, chunk, native_rate):
        # Process a chunk of audio
        # Skip if recognizer not ready
        if not self.recognizer:
            return
        
        # Resample to 16kHz if needed
        chunk = self.resample_to_16k(chunk, native_rate)
        
        # Convert float32 to int16 for Vosk
        audio_int16 = (chunk * 32767).astype(np.int16)
        
        # Feed to Vosk recognizer
        if self.recognizer.AcceptWaveform(audio_int16.tobytes()):
            # Final result - only process complete results
            result = json.loads(self.recognizer.Result())
            text = result.get("text", "").lower().strip()
            
            if text:
                self.process_transcription(text)
                
    def extract_intensity(self, text):
        # Extract intensity value from text, either as digits or written words
        match = re.search(r"\b(\d{1,3})\b", text)
        if match:
            return int(match.group(1))
        
        # Then convert written number words using word2number library
        try:
            # Extract all words that could be numbers
            words = text.lower().split()
            number_words = []
            number_keywords = {'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
                              'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 
                              'seventeen', 'eighteen', 'nineteen', 'twenty', 'thirty', 'forty', 'fifty',
                              'sixty', 'seventy', 'eighty', 'ninety', 'hundred', 'and'}
            
            # Collect consecutive words that might form a number
            for word in words:
                if word in number_keywords:
                    number_words.append(word)
                elif number_words:
                    # Try to convert accumulated words
                    try:
                        intensity = w2n.word_to_num(' '.join(number_words))
                        return intensity
                    except:
                        number_words = []
            
            # Try remaining words
            if number_words:
                try:
                    intensity = w2n.word_to_num(' '.join(number_words))
                    return intensity
                except:
                    pass
        except:
            pass
        
        return None
    
    def process_transcription(self, text: str) -> None:
        # Process transcribed text for wake word and commands
        # Skip empty results
        if not text:
            self.has_speech = False
            return
        
        self.last_command_text = text
        self.log_message(f"Heard: {text}")
        
        # Check for wake word and command
        if self.config["wake_word"] in text:
            intensity = self.extract_intensity(text)
            if intensity is not None:
                self.send_shock(intensity) 
                self.reset_state()
            else:
                self.log_message("Wake word heard, no intensity")
            
    def resample_to_16k(self, audio, src_rate):
        # Resample to 16khz
        target_rate = 16000
        if src_rate == target_rate:
            return audio
        duration = len(audio) / src_rate
        target_len = int(duration * target_rate)
        x_old = np.linspace(0, duration, len(audio), endpoint=False)
        x_new = np.linspace(0, duration, target_len, endpoint=False)
        return np.interp(x_new, x_old, audio).astype(np.float32)
        
    def reset_state(self):
        # Reset all state variables
        self.last_command_text = ""
        self.last_speech_time = None
        # Reset Vosk recognizer for fresh state
        if self.recognizer:
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.recognizer.SetWords(True)
        
    def send_shock(self, intensity: int) -> None:
        # Send shock command to API
        now = time.time()
        if now - self.last_action_time < self.config["cooldown_seconds"]:
            self.log_message("Command heard, in cooldown", level="WARNING")
            return
        
        intensity = max(0, min(intensity, self.config["max_intensity"]))
        
        payload = {
            "shocks": [{
                "id": self.config["control_id"],
                "type": "Shock",
                "intensity": intensity,
                "duration": int(self.config["duration_ms"])
            }],
            "customName": "PupShockVoice"
        }
        
        try:
            response = requests.post(
                "https://api.openshock.app/2/shockers/control",
                headers={
                    "OpenShockToken": self.config["api_token"],
                    "Content-Type": "application/json",
                    "User-Agent": "PupShockVoice/1.0"
                },
                json=payload,
                timeout=5
            )
            
            self.log_message(f"Shock {intensity}% - HTTP {response.status_code}")
            
            if response.ok:
                self.last_action_time = now
            else:
                self.log_message(f"API Error: {response.text}", level="ERROR")
                
        except Exception as e:
            self.log_message(f"Failed to send shock: {e}", level="ERROR")
            
    def test_api(self):
       # Test API by sending 10% shock
        if not self.config["api_token"] or not self.config["control_id"]:
            self.log_message("Please enter API token and Control ID first!", level="ERROR")
            return
        
        self.log_message("Testing API connection...")
        self.send_shock(10)
        
    def minimize_to_tray(self):
        # Minimize app to system tray
        self.root.withdraw()
        
        if not self.tray_icon:
            # Create tray icon
            image = self.create_tray_icon()
            menu = Menu(
                MenuItem("Show", self.show_window),
                MenuItem("Exit", self.quit_app)
            )
            self.tray_icon = Icon("PupShockVoice", image, "PupShock Voice", menu)
            
            # Run in separate thread
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        
    def get_resource_path(self, relative_path):
        # Get resource path for both development and PyInstaller execution
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller executable
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        else:
            # Running in dev
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_path)
    
    def _create_fallback_icon(self):
        # Create fallback icon if icon file is missing
        width = 64
        height = 64
        image = Image.new('RGB', (width, height), color='black')
        dc = ImageDraw.Draw(image)
        dc.rectangle([8, 8, width-8, height-8], fill='blue')
        dc.text((width//2-10, height//2-6), "VS", fill='white')
        return image
    
    def set_window_icon(self):
        # Set window icon from file
        try:
            icon_path = self.get_resource_path('myicon.ico')
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
            else:
                print(f"Icon file not found at {icon_path}")
        except Exception as e:
            print(f"Error loading window icon: {e}")
    
    def create_tray_icon(self):
        # Create tray icon from file
        try:
            icon_path = self.get_resource_path('myicon.ico')
            if os.path.exists(icon_path):
                # Load icon
                image = Image.open(icon_path)
                return image
            else:
                print(f"Icon file not found at {icon_path}")
                return self._create_fallback_icon()
        except Exception as e:
            print(f"Error loading tray icon: {e}")
            return self._create_fallback_icon()
        
    def show_window(self):
        # Show window from tray
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        
    def quit_app(self):
        # Quit application
        if self.tray_icon:
            self.tray_icon.stop()
        self.on_closing()
        
    def on_closing(self):
        # Handle window close
        if self.running:
            self.stop_listening()
        
        self.save_config()
        self.root.destroy()
        
        if self.tray_icon:
            self.tray_icon.stop()
        
        sys.exit(0)
        
    def run(self):
        # Run application
        self.log_message("Application started")
        self.log_message(f"Available audio devices:")
        for device in self.audio_devices:
            self.log_message(f"  {device}")
        
        self.root.mainloop()


if __name__ == "__main__":
    app = VoiceShockApp()
    app.run()