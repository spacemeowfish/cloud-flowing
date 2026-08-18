"""Composition root for the application and its replaceable modules."""

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field

from agent_platform.adapters import DisabledFileOpener, MockWeatherConnector, SystemFileOpener, ZipVoiceReference, ZipVoiceSpeechSynthesizer
from agent_platform.adapters.notifications import windows_toast
from agent_platform.config import Settings
from agent_platform.core.agent_core import AgentCore
from agent_platform.core.audit_service import AuditService
from agent_platform.core.connection_manager import ConnectionManager
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.edge_cloud_router import EdgeCloudRouter
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.core.policy_engine import PolicyEngine
from agent_platform.core.resource_monitor import ResourceMonitor
from agent_platform.core.session_manager import SessionManager
from agent_platform.core.speech_output import DisabledSpeechSynthesizer, SpeechOutputService
from agent_platform.core.task_api import TaskAPI
from agent_platform.core.tool_executor import ToolExecutor
from agent_platform.core.tool_registry import ToolRegistry
from agent_platform.core.voice_input import VoiceInputService
from agent_platform.tools import FileSearchTool, GeneralChatTool, KnowledgeBaseTool, MeetingNotesTool, ReminderTool, ScheduleTool, TextProcessingTool, TodoTool


@dataclass
class ApplicationContainer:
    settings: Settings
    store: SessionManager
    tasks: TaskAPI
    gateway: ModelGateway
    classifier: DataClassificationService
    audit: AuditService
    registry: ToolRegistry
    agent: AgentCore
    connections: ConnectionManager
    knowledge: KnowledgeBaseTool
    reminders: ReminderTool
    todos: TodoTool
    schedules: ScheduleTool
    speech: SpeechOutputService
    voice: VoiceInputService
    background_tasks: set[asyncio.Task[object]] = field(default_factory=set)

    @classmethod
    def build(cls, settings: Settings) -> "ApplicationContainer":
        classifier = DataClassificationService()
        store = SessionManager(settings.database_path)
        tasks = TaskAPI(store)
        gateway = ModelGateway.from_settings(settings)
        audit = AuditService(
            settings.audit_dir,
            classifier,
            retention_days=settings.retention_days,
            flush_size=settings.audit_flush_size,
        )
        opener = SystemFileOpener() if settings.file_open_enabled else DisabledFileOpener()
        knowledge = KnowledgeBaseTool(
            settings.document_roots,
            settings.database_path.with_name("knowledge.db"),
            classifier,
        )
        reminders = ReminderTool(settings.database_path.with_name("reminders.db"), settings.timezone, callback=windows_toast)
        todos = TodoTool(settings.database_path.with_name("todos.db"), settings.timezone)
        schedules = ScheduleTool(settings.database_path.with_name("schedules.db"), settings.timezone, callback=windows_toast)
        registry = ToolRegistry()
        for tool in (
            FileSearchTool(settings.document_roots, opener),
            knowledge,
            reminders,
            todos,
            schedules,
            GeneralChatTool(gateway),
            TextProcessingTool(gateway),
            MeetingNotesTool(settings.document_roots, settings.meeting_output_dir, classifier),
        ):
            registry.register(tool)
        registry.freeze()
        executor = ToolExecutor(registry, idempotency_ttl_seconds=settings.idempotency_ttl_seconds)
        resources = ResourceMonitor(settings.resource_mode)
        agent = AgentCore(
            tasks=tasks,
            gateway=gateway,
            registry=registry,
            executor=executor,
            classifier=classifier,
            policy=PolicyEngine(),
            router=EdgeCloudRouter(classifier),
            resources=resources,
            audit=audit,
            network_available=settings.network_available,
        )
        connections = ConnectionManager(classifier)
        connections.register(MockWeatherConnector())
        connections.freeze()
        if settings.tts_provider == "zipvoice":
            synthesizer = ZipVoiceSpeechSynthesizer(
                model_dir=settings.zipvoice_model_dir,
                vocoder_path=settings.zipvoice_vocoder_path,
                reference_audio_path=settings.zipvoice_reference_audio_path,
                reference_text=settings.zipvoice_reference_text,
                voices=tuple(
                    ZipVoiceReference(
                        id=voice.id,
                        label=voice.label,
                        audio_path=voice.reference_audio_path,
                        text=voice.reference_text,
                    )
                    for voice in settings.zipvoice_voices
                ),
                default_voice_id=settings.zipvoice_default_voice_id,
                num_threads=settings.zipvoice_num_threads,
                speed=settings.zipvoice_speed,
                num_steps=settings.zipvoice_num_steps,
            )
        else:
            synthesizer = DisabledSpeechSynthesizer()
        speech = SpeechOutputService(
            tasks=tasks,
            synthesizer=synthesizer,
            output_dir=settings.tts_output_dir,
            max_chars=settings.tts_max_chars,
            keep_versions=settings.tts_keep_versions,
        )
        voice = VoiceInputService(settings)
        return cls(settings, store, tasks, gateway, classifier, audit, registry, agent, connections, knowledge, reminders, todos, schedules, speech, voice)

    async def initialize(self) -> None:
        await self.tasks.initialize()
        await self.store.purge_expired(self.settings.retention_days)
        await self.audit.purge_expired()
        await self.reminders.start_scheduler()
        await self.schedules.start_scheduler()
        if self.settings.voice_enabled and self.settings.voice_model_dir.is_dir():
            # Load the transcription model in the background so the first
            # push-to-talk recording does not pay the one-time cold start.
            self.spawn(asyncio.to_thread(self.voice.prewarm))

    def spawn(self, coroutine: Coroutine[object, object, object]) -> None:
        task = asyncio.create_task(coroutine)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def close(self) -> None:
        if self.background_tasks:
            done, pending = await asyncio.wait(self.background_tasks, timeout=5)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        await self.reminders.stop_scheduler()
        await self.schedules.stop_scheduler()
        self.reminders.close()
        self.todos.close()
        self.schedules.close()
        self.knowledge.close()
        await self.audit.flush()
        await self.connections.close()
        await self.gateway.close()
        await self.speech.close()
        await self.voice.close()
        await self.store.close()


__all__ = ["ApplicationContainer"]
