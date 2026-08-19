"""GUI Integration Components for AiR LLM Library.

Shows how to integrate PhaseWiseLoader into Shadow's GUI components
(dashboard.py and ide/tab.py).
"""

from typing import Optional, Callable
from .core import PhaseWiseLoader
from .models import Phase


class PhaseStatusWidget:
    """Widget showing current phase, memory pressure, and available models.

    Intended for integration into gui/dashboard.py status bar.
    """

    def __init__(self, loader: PhaseWiseLoader):
        self.loader = loader
        self.update_callback: Optional[Callable] = None

    def get_phase_label(self) -> str:
        """Get current phase as display label."""
        phase = self.loader.get_current_phase()
        phase_names = {
            Phase.INIT: "Init",
            Phase.READY: "Ready",
            Phase.WORKING: "Working",
            Phase.ADVANCED: "Advanced",
        }
        return f"Phase: {phase_names.get(phase, str(phase))}"

    def get_memory_label(self) -> str:
        """Get memory pressure indicator."""
        mem_info = self.loader.get_memory_info()
        pressure = mem_info["pressure"]

        pressure_icons = {
            "low": "🟢",      # Green
            "moderate": "🟡",  # Yellow
            "high": "🔴",      # Red
        }
        icon = pressure_icons.get(pressure, "⚪")
        available = mem_info["system_available_gb"]
        return f"Memory: {icon} {available:.1f}GB free"

    def get_loaded_models_label(self) -> str:
        """Get loaded models display."""
        models = self.loader.get_loaded_models()
        if not models:
            return "No models loaded"
        return f"Loaded: {', '.join(models[:2])}" + (
            f"+{len(models) - 2}" if len(models) > 2 else ""
        )

    def get_all_status(self) -> dict:
        """Get all status information."""
        return {
            "phase": self.get_phase_label(),
            "memory": self.get_memory_label(),
            "models": self.get_loaded_models_label(),
        }


class ModelSelectorComboBox:
    """ComboBox widget for selecting models per phase.

    Intended for integration into gui/ide/ai_panel.py.
    """

    def __init__(self, loader: PhaseWiseLoader, phase: Phase):
        self.loader = loader
        self.phase = phase
        self._current_model = None
        self._update_callback: Optional[Callable] = None

    def get_available_models(self) -> list:
        """Get available models for this phase."""
        from .device_profile import DeviceProfileManager
        return DeviceProfileManager.get_models_for_phase(
            self.loader.device_profile, self.phase
        )

    def set_model(self, model: str) -> None:
        """Set which model to use for this phase."""
        try:
            self.loader.set_phase_model(self.phase, model)
            self._current_model = model
            if self._update_callback:
                self._update_callback(model)
        except ValueError as e:
            raise ValueError(f"Cannot set model for phase {self.phase}: {e}")

    def get_selected_model(self) -> str:
        """Get currently selected model."""
        if not self._current_model:
            models = self.get_available_models()
            if models:
                self._current_model = models[0]
        return self._current_model

    def on_model_changed(self, callback: Callable[[str], None]) -> None:
        """Register callback for when model selection changes."""
        self._update_callback = callback


class UnloadModelButton:
    """Button to unload all models and free memory.

    Intended for integration into gui/ide/ai_panel.py.
    """

    def __init__(self, loader: PhaseWiseLoader):
        self.loader = loader

    def click(self) -> str:
        """Handle button click - unload all models."""
        unloaded = self.loader.unload_all()
        if unloaded:
            return f"Unloaded {len(unloaded)} model(s): {', '.join(unloaded)}"
        else:
            return "No models to unload"


# ============================================================================
# Example Integration Code for gui/dashboard.py
# ============================================================================

DASHBOARD_INTEGRATION_EXAMPLE = '''
# In gui/dashboard.py, MainWindow.__init__():

from assistant.air_llm import PhaseWiseLoader
from assistant.air_llm.gui_integration import PhaseStatusWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # ... existing initialization ...

        # Initialize AiR LLM loader
        self.phase_loader = PhaseWiseLoader()

        # Initialize ChatEngine with phase loader
        from assistant.chat_engine import ChatEngine
        self.chat_engine = ChatEngine(store, phase_loader=self.phase_loader)

        # Add phase status to status bar
        self.phase_status = PhaseStatusWidget(self.phase_loader)
        self.phase_label = QLabel(self.phase_status.get_phase_label())
        self.memory_label = QLabel(self.phase_status.get_memory_label())

        self.statusBar().addWidget(self.phase_label)
        self.statusBar().addStretch()
        self.statusBar().addWidget(self.memory_label)

        # Update status periodically
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_phase_status)
        self.status_timer.start(1000)  # Update every second

    def _update_phase_status(self):
        """Update phase and memory status display."""
        self.phase_label.setText(self.phase_status.get_phase_label())
        self.memory_label.setText(self.phase_status.get_memory_label())
'''

# ============================================================================
# Example Integration Code for gui/ide/ai_panel.py
# ============================================================================

IDE_INTEGRATION_EXAMPLE = '''
# In gui/ide/ai_panel.py, AIPanel.__init__():

from assistant.air_llm.gui_integration import ModelSelectorComboBox, UnloadModelButton
from assistant.air_llm.models import Phase

class AIPanel(QWidget):
    def __init__(self, phase_loader):
        super().__init__()

        self.phase_loader = phase_loader

        # Create layouts
        layout = QVBoxLayout()

        # Phase 1 Model Selector
        phase1_layout = QHBoxLayout()
        phase1_layout.addWidget(QLabel("Phase 1 (Fast):"))
        self.phase1_selector = ModelSelectorComboBox(phase_loader, Phase.READY)
        phase1_combo = QComboBox()
        phase1_combo.addItems(self.phase1_selector.get_available_models())
        phase1_combo.currentTextChanged.connect(self.phase1_selector.set_model)
        phase1_layout.addWidget(phase1_combo)
        layout.addLayout(phase1_layout)

        # Phase 2 Model Selector
        if phase_loader.profile_config["available_phases"] >= Phase.WORKING:
            phase2_layout = QHBoxLayout()
            phase2_layout.addWidget(QLabel("Phase 2 (Balanced):"))
            self.phase2_selector = ModelSelectorComboBox(phase_loader, Phase.WORKING)
            phase2_combo = QComboBox()
            phase2_combo.addItems(self.phase2_selector.get_available_models())
            phase2_combo.currentTextChanged.connect(self.phase2_selector.set_model)
            phase2_layout.addWidget(phase2_combo)
            layout.addLayout(phase2_layout)

        # Unload Button
        unload_button = QPushButton("💾 Unload Models")
        self.unload_handler = UnloadModelButton(phase_loader)
        unload_button.clicked.connect(self._on_unload_clicked)
        layout.addWidget(unload_button)

        self.setLayout(layout)

    def _on_unload_clicked(self):
        """Handle unload button click."""
        message = self.unload_handler.click()
        QMessageBox.information(self, "Models Unloaded", message)
'''

# ============================================================================
# Example Integration Code for gui/ide/workers.py
# ============================================================================

WORKERS_INTEGRATION_EXAMPLE = '''
# In gui/ide/workers.py, ChatWorker.run():

from assistant.streaming import stream_chat

class ChatWorker(QThread):
    chunk_ready = pyqtSignal(str)
    finished_ok = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, prompt, model, phase_loader=None, timeout_seconds=180):
        super().__init__()
        self.prompt = prompt
        self.model = model
        self.phase_loader = phase_loader
        self.timeout_seconds = timeout_seconds

    def run(self):
        try:
            # Use phase-aware model selection if loader available
            for chunk in stream_chat(
                self.prompt,
                model=self.model,
                use_case="chat",  # Will auto-select appropriate model
                loader=self.phase_loader,
                timeout_seconds=self.timeout_seconds
            ):
                self.chunk_ready.emit(chunk)
            self.finished_ok.emit()
        except Exception as e:
            self.error.emit(str(e))
'''

# ============================================================================
# Integration Checklist
# ============================================================================

INTEGRATION_CHECKLIST = '''
AiR LLM GUI Integration Checklist
==================================

[ ] 1. Import PhaseWiseLoader in gui/dashboard.py
      Location: Line ~40 (imports section)
      Code: from assistant.air_llm import PhaseWiseLoader

[ ] 2. Initialize loader in MainWindow.__init__()
      Location: Line ~890 (after chat_engine initialization)
      Code: self.phase_loader = PhaseWiseLoader()

[ ] 3. Pass loader to ChatEngine
      Location: Line ~920 (ChatEngine creation)
      Code: engine = ChatEngine(store, phase_loader=self.phase_loader)

[ ] 4. Add phase status widget to status bar
      Location: Line ~950 (status bar setup)
      Code: self.phase_status = PhaseStatusWidget(self.phase_loader)
            self.statusBar().addWidget(self.phase_status_label)

[ ] 5. Update status bar periodically
      Location: Line ~960 (status bar update)
      Code: self.status_timer.timeout.connect(self._update_phase_status)

[ ] 6. Import selectors in gui/ide/ai_panel.py
      Location: Line ~30 (imports section)
      Code: from assistant.air_llm.gui_integration import ModelSelectorComboBox

[ ] 7. Add phase model selectors to AIPanel
      Location: Line ~150 (widget initialization)
      Code: self.phase1_selector = ModelSelectorComboBox(...)
            self.phase2_selector = ModelSelectorComboBox(...)

[ ] 8. Add unload button to AIPanel
      Location: Line ~170 (buttons section)
      Code: self.unload_button = QPushButton("💾 Unload Models")
            self.unload_button.clicked.connect(self._on_unload_clicked)

[ ] 9. Pass loader to ChatWorker
      Location: gui/ide/workers.py, ChatWorker.run()
      Code: for chunk in stream_chat(..., loader=self.phase_loader):

[ ] 10. Update other workers similarly
       Files: PlanWorker, ApplyWorker, ExplainWorker
       Code: Pass phase_loader and use use_case parameter

Estimated Integration Time: 1-2 hours
Complexity: Low (most code is copy-paste)
Testing: All unit tests pass, integration examples provided
'''

if __name__ == "__main__":
    print("AiR LLM GUI Integration Guide")
    print("=" * 70)
    print("\nDashboard Integration Example:")
    print(DASHBOARD_INTEGRATION_EXAMPLE)
    print("\n" + "=" * 70)
    print("\nIDE Panel Integration Example:")
    print(IDE_INTEGRATION_EXAMPLE)
    print("\n" + "=" * 70)
    print("\nWorker Integration Example:")
    print(WORKERS_INTEGRATION_EXAMPLE)
    print("\n" + "=" * 70)
    print("\nIntegration Checklist:")
    print(INTEGRATION_CHECKLIST)
