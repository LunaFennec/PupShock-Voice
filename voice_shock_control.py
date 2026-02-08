import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import sounddevice as sd
import numpy as np
import requests
import queue
import time
import re
import threading
import json
import os
from faster_whisper import WhisperModel
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw
import sys

class VoiceShockApp:
    def __init__(self):
        # Initialize main window
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("dark-blue")
        
        self.root = ctk.CTk()
        self.root.title("PupShock Voice")
        self.root.geometry("900x750")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Set window icon
        self.set_window_icon()
        
        # Load configuration
        self.config_file = "config.json"
        self.load_config()
        
        # State variables
        self.running = False
        self.model = None
        self.stream = None
        self.loopback_stream = None
        self.audio_queue = queue.Queue()
        self.rolling_buffer = np.zeros(0, dtype=np.float32)
        
        # Runtime state
        self.last_action_time = 0
        self.last_transcribe_time = 0
        self.last_command_text = ""
        self.silence_start = None
        self.has_speech = False
        self.last_speech_time = None
        self.command_armed = True
        
        # Audio level for VU meter
        self.current_audio_level = 0
        
        # System tray
        self.tray_icon = None
        
        # Build UI
        self.create_ui()
        
        # Start VU meter update
        self.update_vu_meter()
        
    def load_config(self):
        """Load configuration from file or use defaults"""
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
            "rolling_seconds": 3,
            "transcribe_interval": 0.8,
            "silence_threshold": 0.01,
            "silence_duration": 0.5,
            "state_reset_timeout": 5.0,
            "model_size": "tiny",
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
        """Save current configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            self.log_message("Configuration saved")
        except Exception as e:
            self.log_message(f"Error saving config: {e}", level="ERROR")
            
    def create_ui(self):
        """Create the main UI"""
        # Create notebook (tabbed interface)
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
        
        # Control buttons at bottom
        self.create_control_panel()
        
    def create_console_tab(self):
        """Create console output tab"""
        tab = self.notebook.tab("Console")
        
        # Console output
        console_frame = ctk.CTkFrame(tab)
        console_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(console_frame, text="Console Output", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=5)
        
        # Text widget with scrollbar
        text_frame = ctk.CTkFrame(console_frame)
        text_frame.pack(fill="both", expand=True, pady=5)
        
        self.console_text = tk.Text(text_frame, wrap=tk.WORD, 
                                   bg="#2b2b2b", fg="#ffffff",
                                   font=("Consolas", 10))
        scrollbar = ctk.CTkScrollbar(text_frame, command=self.console_text.yview)
        self.console_text.configure(yscrollcommand=scrollbar.set)
        
        self.console_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Clear button
        ctk.CTkButton(console_frame, text="Clear Console", 
                     command=self.clear_console).pack(pady=5)
        
    def create_audio_tab(self):
        """Create audio device selection tab"""
        tab = self.notebook.tab("Audio")
        
        # Microphone device selection
        device_frame = ctk.CTkFrame(tab)
        device_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(device_frame, text="Microphone Input Device", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=5)
        
        # Get audio devices (filter to MME on Windows)
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
                # Filter to MME devices on Windows, or show all on other platforms
                if mme_index is None or device['hostapi'] == mme_index:
                    self.audio_devices.append(f"{i}: {device['name']}")
        
        self.device_var = ctk.StringVar(value=self.audio_devices[self.config["audio_device"]] 
                                        if self.config["audio_device"] < len(self.audio_devices) 
                                        else self.audio_devices[0])
        
        device_menu = ctk.CTkOptionMenu(device_frame, variable=self.device_var,
                                       values=self.audio_devices,
                                       command=self.on_device_change)
        device_menu.pack(pady=10, padx=20, fill="x")
        
        # Loopback (Speaker) device selection
        loopback_frame = ctk.CTkFrame(tab)
        loopback_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(loopback_frame, text="System Audio", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=5)
        
        # Enable loopback checkbox
        self.loopback_enabled_var = ctk.BooleanVar(value=self.config["loopback_enabled"])
        ctk.CTkCheckBox(loopback_frame, text="Enable System Audio", 
                       variable=self.loopback_enabled_var,
                       command=self.on_loopback_toggle).pack(pady=5)
        
        # Get loopback devices (look for Stereo Mix and WASAPI output devices)
        self.loopback_devices = []
        
        # Find WASAPI host API index
        wasapi_index = None
        for i, api in enumerate(host_apis):
            if 'WASAPI' in api['name']:
                wasapi_index = i
                break
        
        # First, look for "Stereo Mix" or similar MME loopback devices
        for i, device in enumerate(sd.query_devices()):
            device_name = device['name'].lower()
            if device["max_input_channels"] > 0 and any(keyword in device_name for keyword in 
                ['stereo mix', 'wave out', 'loopback', 'what u hear', 'what you hear', 'wave out mix']):
                self.loopback_devices.append(f"{i}: {device['name']} (MME Loopback)")
        
        # Add WASAPI output devices (can be used for loopback capture)
        if wasapi_index is not None:
            for i, device in enumerate(sd.query_devices()):
                if device["max_output_channels"] > 0 and device['hostapi'] == wasapi_index:
                    self.loopback_devices.append(f"{i}: {device['name']} (WASAPI)")
        
        # If still no devices found, show all MME input devices as fallback
        if not self.loopback_devices:
            for i, device in enumerate(sd.query_devices()):
                if device["max_input_channels"] > 0:
                    if mme_index is None or device['hostapi'] == mme_index:
                        self.loopback_devices.append(f"{i}: {device['name']} (MME)")
        
        # Fallback message if still nothing found
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
                                 text="Loopback system audio - Requiress stereo mix or WASAPI loopback device.\n If no loopback devices are found, try enabling 'Stereo Mix' in Windows Sound settings.",
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
        """Create settings tab"""
        tab = self.notebook.tab("Settings")
        
        # Scrollable frame
        scroll_frame = ctk.CTkScrollableFrame(tab)
        scroll_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Wake Word
        wake_frame = ctk.CTkFrame(scroll_frame)
        wake_frame.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(wake_frame, text="Wake Word:").pack(side="left", padx=5)
        self.wake_word_var = ctk.StringVar(value=self.config["wake_word"])
        ctk.CTkEntry(wake_frame, textvariable=self.wake_word_var, 
                    width=200).pack(side="left", padx=5)
        
        # Model Size
        model_frame = ctk.CTkFrame(scroll_frame)
        model_frame.pack(fill="x", pady=5, padx=5)
        ctk.CTkLabel(model_frame, text="Model Size:").pack(side="left", padx=5)
        self.model_var = ctk.StringVar(value=self.config["model_size"])
        ctk.CTkOptionMenu(model_frame, variable=self.model_var,
                         values=["tiny", "base", "small", "medium", "large"]).pack(side="left", padx=5)
        
        # Create sliders for numeric settings
        self.create_slider(scroll_frame, "Max Intensity (%)", "max_intensity", 0, 100, 1)
        self.create_slider(scroll_frame, "Duration (ms)", "duration_ms", 100, 5000, 100)
        self.create_slider(scroll_frame, "Cooldown (seconds)", "cooldown_seconds", 1, 60, 1)
        self.create_slider(scroll_frame, "Rolling Window (seconds)", "rolling_seconds", 1, 10, 1)
        self.create_slider(scroll_frame, "Transcribe Interval (seconds)", "transcribe_interval", 
                          0.1, 2.0, 0.1)
        self.create_slider(scroll_frame, "Silence Threshold", "silence_threshold", 
                          0.001, 0.1, 0.001)
        self.create_slider(scroll_frame, "Silence Duration (seconds)", "silence_duration", 
                          0.1, 2.0, 0.1)
        
        # Save button
        ctk.CTkButton(scroll_frame, text="Save Settings", 
                     command=self.save_settings).pack(pady=20)
        
    def create_slider(self, parent, label, config_key, min_val, max_val, step):
        """Helper to create a labeled slider"""
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
        """Create API configuration tab"""
        tab = self.notebook.tab("API")
        
        frame = ctk.CTkFrame(tab)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(frame, text="OpenShock API Configuration", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        
        # API Token
        token_frame = ctk.CTkFrame(frame)
        token_frame.pack(fill="x", pady=10, padx=20)
        ctk.CTkLabel(token_frame, text="API Token:", width=100).pack(side="left", padx=5)
        self.api_token_var = ctk.StringVar(value=self.config["api_token"])
        ctk.CTkEntry(token_frame, textvariable=self.api_token_var, 
                    show="*", width=400).pack(side="left", fill="x", expand=True, padx=5)
        
        # Control ID
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
        """Create control buttons at bottom"""
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
        """Handle audio device change"""
        device_index = int(selection.split(":")[0])
        self.config["audio_device"] = device_index
        self.log_message(f"Audio device changed to: {selection}")
        
    def on_loopback_toggle(self):
        """Handle loopback enable/disable"""
        self.config["loopback_enabled"] = self.loopback_enabled_var.get()
        status = "enabled" if self.config["loopback_enabled"] else "disabled"
        self.log_message(f"Speaker loopback {status}")
        
    def on_loopback_device_change(self, selection):
        """Handle loopback device change"""
        device_index = int(selection.split(":")[0])
        self.config["loopback_device"] = device_index
        self.log_message(f"Loopback device changed to: {selection}")
        
    def save_settings(self):
        """Save all settings from UI to config"""
        self.config["wake_word"] = self.wake_word_var.get()
        self.config["model_size"] = self.model_var.get()
        self.config["api_token"] = self.api_token_var.get()
        self.config["control_id"] = self.control_id_var.get()
        self.config["loopback_enabled"] = self.loopback_enabled_var.get()
        self.config["loopback_mix_ratio"] = self.mix_ratio_slider.get()
        
        # Get slider values
        slider_keys = ["max_intensity", "duration_ms", "cooldown_seconds", 
                      "rolling_seconds", "transcribe_interval", "silence_threshold", 
                      "silence_duration"]
        
        for key in slider_keys:
            slider = getattr(self, f"{key}_slider")
            self.config[key] = slider.get()
        
        self.save_config()
        
    def save_api_settings(self):
        """Save API settings only"""
        self.config["api_token"] = self.api_token_var.get()
        self.config["control_id"] = self.control_id_var.get()
        self.save_config()
        
    def log_message(self, message, level="INFO"):
        """Add message to console"""
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] [{level}] {message}\n"
        
        self.console_text.insert(tk.END, formatted)
        self.console_text.see(tk.END)
        
        # Also print to stdout
        print(formatted.strip())
        
    def clear_console(self):
        """Clear console output"""
        self.console_text.delete(1.0, tk.END)
        
    def update_vu_meter(self):
        """Update VU meter display"""
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
        """Start/stop listening"""
        if not self.running:
            self.start_listening()
        else:
            self.stop_listening()
            
    def start_listening(self):
        """Start the audio processing"""
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
        """Stop the audio processing"""
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
        """Main processing thread"""
        try:
            # Load model
            self.log_message(f"Loading {self.config['model_size']} model...")
            self.model = WhisperModel(self.config["model_size"], 
                                     device="cpu", compute_type="int8")
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
            
            # Start loopback stream if enabled
            if self.config["loopback_enabled"]:
                try:
                    loopback_index = self.config["loopback_device"]
                    loopback_info = sd.query_devices(loopback_index)
                    
                    # Check if this is a WASAPI output device being used for loopback
                    is_wasapi_output = (loopback_info["max_output_channels"] > 0 and 
                                       loopback_info["max_input_channels"] == 0)
                    
                    if is_wasapi_output:
                        # WASAPI loopback mode - open output device as input
                        self.log_message("Using WASAPI loopback mode")
                        loopback_rate = int(loopback_info['default_samplerate'])
                        
                        # For WASAPI loopback, we open it as an input despite being an output device
                        self.loopback_stream = sd.InputStream(
                            samplerate=loopback_rate,
                            channels=1,
                            dtype="float32",
                            blocksize=self.config["chunk_size"],
                            device=loopback_index,
                            callback=self.loopback_audio_callback
                        )
                    else:
                        # Regular input device (Stereo Mix, etc.)
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
        """Audio input callback"""
        if status:
            self.log_message(f"Audio status: {status}", level="WARNING")
        
        audio_data = indata[:, 0].copy()
        
        # If loopback is enabled, apply mic mix ratio (inverse of speaker ratio)
        if self.config["loopback_enabled"]:
            mic_ratio = 1.0 - self.config["loopback_mix_ratio"]
            audio_data = audio_data * mic_ratio
        
        self.audio_queue.put(audio_data)
        
        # Update VU meter
        rms = np.sqrt(np.mean(audio_data ** 2))
        self.current_audio_level = min(1.0, rms * 10)  # Scale for visibility
        
    def loopback_audio_callback(self, indata, frames, time_info, status):
        """Loopback audio input callback"""
        if status:
            self.log_message(f"Loopback status: {status}", level="WARNING")
        
        loopback_data = indata[:, 0].copy()
        
        # Apply speaker mix ratio
        speaker_ratio = self.config["loopback_mix_ratio"]
        loopback_data = loopback_data * speaker_ratio
        
        # Add to queue (will be mixed with mic audio)
        self.audio_queue.put(loopback_data)
        
    def process_audio_chunk(self, chunk, native_rate):
        """Process a chunk of audio"""
        # Compute RMS for silence detection
        rms = np.sqrt(np.mean(chunk ** 2))
        
        # Track silence periods
        now = time.time()
        is_silent = rms < self.config["silence_threshold"]
        
        if is_silent:
            if self.silence_start is None:
                self.silence_start = now
        else:
            self.silence_start = None
            self.has_speech = True
            self.last_speech_time = now
        
        # Timeout protection
        if self.last_speech_time and (now - self.last_speech_time > self.config["state_reset_timeout"]):
            self.reset_state()
            self.command_armed = True
        
        # Resample and buffer audio
        chunk = self.resample_to_16k(chunk, native_rate)
        self.rolling_buffer = np.concatenate((self.rolling_buffer, chunk))
        
        # Keep only last ROLLING_SECONDS of audio
        max_len = int(self.config["sample_rate"] * self.config["rolling_seconds"])
        if len(self.rolling_buffer) > max_len:
            self.rolling_buffer = self.rolling_buffer[-max_len:]
        
        # Only transcribe after silence following speech, or at regular intervals
        silence_elapsed = (now - self.silence_start) if self.silence_start else 0
        time_since_last = now - self.last_transcribe_time
        
        should_transcribe = (
            (self.has_speech and silence_elapsed > self.config["silence_duration"]) or
            (self.command_armed and time_since_last > self.config["transcribe_interval"] and self.has_speech)
        )
        
        if not should_transcribe:
            return
        
        # Skip if buffer is mostly silence
        buffer_rms = np.sqrt(np.mean(self.rolling_buffer ** 2))
        if buffer_rms < self.config["silence_threshold"]:
            self.has_speech = False
            return
        
        self.last_transcribe_time = now
        
        # Transcribe
        if self.model is None:
            self.log_message("Model not loaded yet, unable to transcribe", level="WARNING")
            return
        
        segments, _ = self.model.transcribe(
            self.rolling_buffer,
            language="en",
            vad_filter=True,
            beam_size=1
        )
        text = " ".join(seg.text.lower().strip() for seg in segments).strip()
        
        # Skip empty results
        if not text:
            self.has_speech = False
            return
        
        # Skip exact duplicates
        if text == self.last_command_text:
            return
        
        # Skip if new text is just an extension of previous
        if self.last_command_text and text.startswith(self.last_command_text):
            self.last_command_text = text
            return
        
        self.last_command_text = text
        self.log_message(f"Heard: {text}")
        
        # Check for wake word and command
        if self.config["wake_word"] in text and self.command_armed:
            match = re.search(r"\b(\d{1,3})\b", text)
            if match:
                intensity = int(match.group(1))
                self.send_shock(intensity)
                
                # Disarm and clear
                self.command_armed = False
                self.reset_state()
            else:
                self.log_message("Wake word heard, no intensity")
                self.has_speech = False
        else:
            self.has_speech = False
        
        # Re-arm on extended silence
        if silence_elapsed > self.config["silence_duration"] * 2:
            if not self.command_armed:
                self.log_message("Re-arming on silence")
            self.command_armed = True
            self.has_speech = False
            
    def resample_to_16k(self, audio, src_rate):
        """Resample audio to 16kHz"""
        target_rate = self.config["sample_rate"]
        if src_rate == target_rate:
            return audio
        duration = len(audio) / src_rate
        target_len = int(duration * target_rate)
        x_old = np.linspace(0, duration, len(audio), endpoint=False)
        x_new = np.linspace(0, duration, target_len, endpoint=False)
        return np.interp(x_new, x_old, audio).astype(np.float32)
        
    def reset_state(self):
        """Reset all state variables"""
        self.has_speech = False
        self.silence_start = None
        self.last_command_text = ""
        self.last_speech_time = None
        self.rolling_buffer = np.zeros(0, dtype=np.float32)
        
    def send_shock(self, intensity):
        """Send shock command to API"""
        now = time.time()
        if now - self.last_action_time < self.config["cooldown_seconds"]:
            self.log_message("Cooldown active, ignoring command", level="WARNING")
            return
        
        intensity = max(0, min(intensity, self.config["max_intensity"]))
        
        payload = {
            "shocks": [{
                "id": self.config["control_id"],
                "type": "Shock",
                "intensity": intensity,
                "duration": int(self.config["duration_ms"])
            }],
            "customName": "VoiceControl"
        }
        
        try:
            response = requests.post(
                "https://api.openshock.app/2/shockers/control",
                headers={
                    "OpenShockToken": self.config["api_token"],
                    "Content-Type": "application/json",
                    "User-Agent": "OpenShockVoiceClient/1.0"
                },
                json=payload,
                timeout=5
            )
            
            self.log_message(f"Shock {intensity}% | HTTP {response.status_code}")
            
            if response.ok:
                self.last_action_time = now
            else:
                self.log_message(f"API Error: {response.text}", level="ERROR")
                
        except Exception as e:
            self.log_message(f"Failed to send shock: {e}", level="ERROR")
            
    def test_api(self):
        """Test API connection with 10% shock"""
        if not self.config["api_token"] or not self.config["control_id"]:
            self.log_message("Please enter API token and Control ID first!", level="ERROR")
            return
        
        self.log_message("Testing API connection...")
        self.send_shock(10)
        
    def minimize_to_tray(self):
        """Minimize application to system tray"""
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
        """Get resource path for both development and PyInstaller execution"""
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller executable
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        else:
            # Running in development
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, relative_path)
    
    def set_window_icon(self):
        """Set the window icon from the .ico file"""
        try:
            icon_path = self.get_resource_path('myicon.ico')
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
            else:
                print(f"Icon file not found at {icon_path}")
        except Exception as e:
            print(f"Error loading window icon: {e}")
    
    def create_tray_icon(self):
        """Create system tray icon from .ico file"""
        try:
            icon_path = self.get_resource_path('myicon.ico')
            if os.path.exists(icon_path):
                # Load icon from .ico file
                image = Image.open(icon_path)
                return image
            else:
                print(f"Icon file not found at {icon_path}, using fallback")
                # Fallback: Create a simple icon
                width = 64
                height = 64
                image = Image.new('RGB', (width, height), color='black')
                dc = ImageDraw.Draw(image)
                dc.rectangle([8, 8, width-8, height-8], fill='blue')
                dc.text((width//2-10, height//2-6), "VS", fill='white')
                return image
        except Exception as e:
            print(f"Error loading tray icon: {e}")
            # Fallback: Create a simple icon
            width = 64
            height = 64
            image = Image.new('RGB', (width, height), color='black')
            dc = ImageDraw.Draw(image)
            dc.rectangle([8, 8, width-8, height-8], fill='blue')
            dc.text((width//2-10, height//2-6), "VS", fill='white')
            return image
        
    def show_window(self):
        """Show window from tray"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        
    def quit_app(self):
        """Quit application"""
        if self.tray_icon:
            self.tray_icon.stop()
        self.on_closing()
        
    def on_closing(self):
        """Handle window close"""
        if self.running:
            self.stop_listening()
        
        self.save_config()
        self.root.destroy()
        
        if self.tray_icon:
            self.tray_icon.stop()
        
        sys.exit(0)
        
    def run(self):
        """Run the application"""
        self.log_message("Application started")
        self.log_message(f"Available audio devices:")
        for device in self.audio_devices:
            self.log_message(f"  {device}")
        
        self.root.mainloop()


if __name__ == "__main__":
    app = VoiceShockApp()
    app.run()
