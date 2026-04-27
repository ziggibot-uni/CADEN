from caden.errors import (
    BootError,
    CadenError,
    ConfigError,
    DBError,
    EmbedError,
    GoogleSyncError,
    LLMAborted,
    LLMError,
    LLMRepairError,
    RaterError,
    SchedulerError,
    SprocketError,
    UIError,
)


def test_public_caden_error_hierarchy_exposes_documented_subsystem_classes():
    expected = {
        ConfigError,
        BootError,
        DBError,
        EmbedError,
        LLMError,
        LLMAborted,
        LLMRepairError,
        RaterError,
        SchedulerError,
        GoogleSyncError,
        SprocketError,
        UIError,
    }

    def _all_subclasses(cls):
        direct = set(cls.__subclasses__())
        nested = set().union(*(_all_subclasses(subclass) for subclass in direct)) if direct else set()
        return direct | nested

    subclasses = _all_subclasses(CadenError)

    assert expected.issubset(subclasses)
    assert issubclass(LLMAborted, LLMError)
    assert issubclass(LLMRepairError, LLMError)