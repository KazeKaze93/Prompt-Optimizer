import os
import json
import threading
import datetime
import customtkinter as ctk
import google.generativeai as genai
from typing import Optional

# --- Config ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
CONFIG_FILE = "user_config.json"
HISTORY_FILE = "history.json"

class GeminiKeyDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Gemini Setup")
        self.geometry("450x200")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.transient(parent)
        self.grab_set()
        
        self.parent_app = parent
        self.new_key = None

        ctk.CTkLabel(self, text="Enter Google Gemini API Key:", font=("Roboto", 14, "bold")).pack(pady=(20, 10))
        
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(pady=5)

        self.entry = ctk.CTkEntry(input_frame, width=300, placeholder_text="AIzaSy...")
        self.entry.pack(side="left", padx=(0, 5))
        
        self.btn_paste = ctk.CTkButton(
            input_frame, text="Paste", width=60, fg_color="#333333", 
            command=self.paste_from_clipboard
        )
        self.btn_paste.pack(side="left")

        self.entry.bind("<Control-v>", self.paste_event)
        self.entry.bind("<Button-3>", self.paste_from_clipboard)
        self.entry.focus_force()
        self.entry.bind("<Return>", lambda e: self.save_and_close())

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=20)
        ctk.CTkButton(btn_frame, text="Save Key", command=self.save_and_close, fg_color="#106A43").pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Cancel", command=self.destroy, fg_color="#444444", width=80).pack(side="left", padx=10)

    def paste_from_clipboard(self, event=None):
        try:
            self.entry.delete(0, "end")
            self.entry.insert(0, self.clipboard_get())
        except: pass

    def paste_event(self, event):
        self.paste_from_clipboard()
        return "break"

    def save_and_close(self):
        key = self.entry.get().strip()
        if key:
            self.new_key = key
            self.destroy()

class PromptOptimizerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Gemini Prompt Optimizer")
        self.geometry("900x800")
        
        self.google_key: Optional[str] = None
        self.current_models = {}
        self.history_data = []

        self._setup_ui()
        self.after(200, self._startup_sequence)

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.tab_main = self.tabview.add("Optimizer")
        self.tab_history = self.tabview.add("History")
        
        t = self.tab_main
        t.grid_columnconfigure(0, weight=1)
        t.grid_rowconfigure(3, weight=1) 
        t.grid_rowconfigure(6, weight=1)

        # 1. Header
        frame_top = ctk.CTkFrame(t, fg_color="transparent")
        frame_top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(frame_top, text="Gemini Model:", font=("Roboto", 14, "bold")).pack(side="left", padx=5)
        self.model_var = ctk.StringVar(value="Loading...")
        self.model_dropdown = ctk.CTkOptionMenu(frame_top, variable=self.model_var, width=250)
        self.model_dropdown.pack(side="left", padx=5)
        ctk.CTkButton(frame_top, text="⟳", width=30, command=self._trigger_refresh_models).pack(side="left", padx=5)
        ctk.CTkButton(frame_top, text="Change Key", command=self._ask_user_for_key, width=100, fg_color="#444444").pack(side="right")

        # 2. Controls
        frame_controls = ctk.CTkFrame(t, fg_color="transparent")
        frame_controls.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        ctk.CTkLabel(frame_controls, text="Creativity (Temp):").pack(side="left", padx=5)
        self.slider_temp = ctk.CTkSlider(frame_controls, from_=0.0, to=1.0, number_of_steps=20, width=200)
        self.slider_temp.set(0.7)
        self.slider_temp.pack(side="left", padx=10)
        self.lbl_temp = ctk.CTkLabel(frame_controls, text="0.7")
        self.lbl_temp.pack(side="left")
        self.slider_temp.configure(command=lambda v: self.lbl_temp.configure(text=f"{v:.2f}"))

        # 3. Input with PASTE BUTTON
        frame_input_head = ctk.CTkFrame(t, fg_color="transparent")
        frame_input_head.grid(row=2, column=0, sticky="ew", padx=5)
        
        ctk.CTkLabel(frame_input_head, text="Dirty Prompt:", anchor="w", text_color="gray").pack(side="left")
        
        # --- ВОТ ОНА, СПАСИТЕЛЬНАЯ КНОПКА ---
        ctk.CTkButton(frame_input_head, text="Paste Input", height=20, width=100, 
                      fg_color="#333333", command=self._paste_to_input).pack(side="right")
        
        self.input_text = ctk.CTkTextbox(t, height=100)
        self.input_text.grid(row=3, column=0, sticky="nsew", padx=5)
        
        # Привязываем Ctrl+V принудительно
        try:
            self.input_text._textbox.bind("<Control-v>", self._paste_event_main)
        except: pass

        # 4. Button
        self.btn_optimize = ctk.CTkButton(
            t, text="OPTIMIZE WITH GEMINI", command=self.start_optimization_thread,
            height=45, font=("Roboto", 15, "bold"), fg_color="#106A43", hover_color="#0C4F32"
        )
        self.btn_optimize.grid(row=4, column=0, sticky="ew", padx=5, pady=15)

        # 5. Output
        frame_out_head = ctk.CTkFrame(t, fg_color="transparent")
        frame_out_head.grid(row=5, column=0, sticky="ew")
        ctk.CTkLabel(frame_out_head, text="Polished Prompt:", anchor="w", text_color="gray").pack(side="left", padx=5)
        self.btn_copy = ctk.CTkButton(frame_out_head, text="📋 Copy", width=80, height=24, fg_color="#333333", command=self._copy_to_clipboard)
        self.btn_copy.pack(side="right", padx=5)

        self.output_text = ctk.CTkTextbox(t, height=150)
        self.output_text.grid(row=6, column=0, sticky="nsew", padx=5)

        # 6. Status
        self.status_bar = ctk.CTkLabel(t, text="System Standby", anchor="w", font=("Consolas", 12))
        self.status_bar.grid(row=7, column=0, sticky="ew", padx=5, pady=(5,0))

        # History
        self.history_scroll = ctk.CTkScrollableFrame(self.tab_history, label_text="Recent Optimizations")
        self.history_scroll.pack(fill="both", expand=True)

    # --- INPUT PASTE LOGIC ---
    def _paste_to_input(self):
        """Ручная вставка кнопкой"""
        try:
            text = self.clipboard_get()
            self.input_text.insert("end", text)
        except: pass

    def _paste_event_main(self, event):
        """Обработка Ctrl+V в главном окне"""
        try:
            text = self.clipboard_get()
            self.input_text.insert("insert", text)
            return "break"
        except: pass

    # --- STARTUP ---
    def _startup_sequence(self):
        self._load_history()
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    self.google_key = data.get("google_key") or data.get("google")
            except: pass

        if not self.google_key:
            self._ask_user_for_key()
        else:
            self._init_gemini()

    def _init_gemini(self):
        if self.google_key:
            try:
                genai.configure(api_key=self.google_key)
                self._trigger_refresh_models()
            except Exception as e:
                self.status_bar.configure(text=f"Auth Error: {e}", text_color="red")
        else:
            self.model_var.set("Key Missing")

    def _ask_user_for_key(self):
        dialog = GeminiKeyDialog(self)
        self.wait_window(dialog)
        if dialog.new_key:
            self.google_key = dialog.new_key
            self._save_config()
            self._init_gemini()

    def _save_config(self):
        with open(CONFIG_FILE, "w") as f: json.dump({"google_key": self.google_key}, f)

    # --- MODELS ---
    def _trigger_refresh_models(self):
        if not self.google_key: return
        self.model_dropdown.configure(state="disabled")
        self.model_var.set("Fetching Gemini models...")
        threading.Thread(target=self._fetch_models_worker, daemon=True).start()

    def _fetch_models_worker(self):
        new_map = {}
        try:
            models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            models.sort(key=lambda x: x.name, reverse=True)
            for m in models:
                clean_name = m.name.replace("models/", "")
                new_map[clean_name] = m.name
        except Exception as e:
            new_map = {f"Error: {str(e)[:20]}": ""}
        self.after(0, self._update_models_ui, new_map)

    def _update_models_ui(self, new_map):
        self.current_models = new_map
        vals = list(new_map.keys())
        self.model_dropdown.configure(values=vals, state="normal")
        if vals:
            default = next((x for x in vals if "flash" in x), vals[0])
            self.model_var.set(default)

    # --- OPTIMIZATION ---
    def start_optimization_thread(self):
        prompt = self.input_text.get("0.0", "end").strip()
        if not prompt: return
        if not self.google_key: self._ask_user_for_key(); return

        ui_choice = self.model_var.get()
        api_model_name = self.current_models.get(ui_choice)
        if not api_model_name: return

        temp = self.slider_temp.get()
        self.btn_optimize.configure(state="disabled", text="GEMINI IS THINKING...")
        self.status_bar.configure(text=f"Sending to {api_model_name}...", text_color="#3B8ED0")
        
        threading.Thread(target=self.run_optimization, args=(api_model_name, prompt, temp), daemon=True).start()

    def run_optimization(self, model_id, user_prompt, temp):
        sys_prompt = "You are an expert Prompt Engineer. Rewrite user prompt using: Persona -> Context -> Task -> Constraints -> Output Format."
        res, t_total, success = "", 0, False

        try:
            model = genai.GenerativeModel(model_id, system_instruction=sys_prompt)
            resp = model.generate_content(
                user_prompt, 
                generation_config=genai.types.GenerationConfig(temperature=temp)
            )
            res = resp.text
            if resp.usage_metadata: t_total = resp.usage_metadata.total_token_count
            success = True
        except Exception as e:
            res = f"Gemini Error: {e}"
        self.after(0, self._finish, res, t_total, success, user_prompt, model_id)

    def _finish(self, text, tokens, success, original, model_id):
        self.output_text.delete("0.0", "end")
        self.output_text.insert("0.0", text)
        self.btn_optimize.configure(state="normal", text="OPTIMIZE WITH GEMINI")
        if success:
            self.status_bar.configure(text=f"Success! Total Tokens: {tokens}", text_color="#106A43")
            self._add_to_history(original, text, model_id, tokens)
        else:
            self.status_bar.configure(text="Optimization Failed", text_color="red")

    # --- UTILS ---
    def _copy_to_clipboard(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.output_text.get("0.0", "end").strip())
            self.btn_copy.configure(text="✅", fg_color="green")
            self.after(1000, lambda: self.btn_copy.configure(text="📋 Copy", fg_color="#333333"))
        except: pass

    def _add_to_history(self, p, r, m, t):
        entry = {"ts": datetime.datetime.now().strftime("%H:%M"), "model": m, "prompt": p, "result": r, "tokens": t}
        self.history_data.insert(0, entry)
        if len(self.history_data)>50: self.history_data.pop()
        with open(HISTORY_FILE, "w") as f: json.dump(self.history_data, f)
        self._render_history_item(entry)

    def _load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f: self.history_data = json.load(f)
            except: pass
        for w in self.history_scroll.winfo_children(): w.destroy()
        for e in self.history_data:
            try: self._render_history_item(e)
            except: continue

    def _render_history_item(self, entry):
        ts = entry.get("ts", entry.get("timestamp", "??:??"))
        prompt = entry.get("prompt", "")
        
        c = ctk.CTkFrame(self.history_scroll, fg_color="#2B2B2B")
        c.pack(fill="x", pady=2, padx=5)
        h = ctk.CTkFrame(c, fg_color="transparent")
        h.pack(fill="x")
        
        ctk.CTkLabel(h, text=f"{ts} | {entry.get('tokens','?')} tok", font=("Arial",10), text_color="gray").pack(side="left")
        ctk.CTkLabel(c, text=prompt[:50]+"...", anchor="w", font=("Arial",12)).pack(fill="x", padx=5)
        ctk.CTkButton(c, text="Load", height=20, fg_color="#444444", command=lambda: self._restore(entry)).pack(fill="x", padx=5, pady=2)

    def _restore(self, e):
        self.tabview.set("Optimizer")
        self.input_text.delete("0.0", "end"); self.input_text.insert("0.0", e.get("prompt",""))
        self.output_text.delete("0.0", "end"); self.output_text.insert("0.0", e.get("result",""))

if __name__ == "__main__":
    app = PromptOptimizerApp()
    app.mainloop()