"""Tests for Model Manager."""

import pytest
from ai_orchestrator.model_manager import ModelManager, ModelCapability


def test_model_manager_init():
    """Test ModelManager initialization."""
    manager = ModelManager()
    assert manager is not None
    assert len(manager.models) > 0


def test_get_best_model_for_code_generation():
    """Test getting best model for code generation."""
    manager = ModelManager()
    model = manager.get_best_model(ModelCapability.CODE_GENERATION)

    assert model is not None
    assert ModelCapability.CODE_GENERATION in model.capabilities


def test_get_available_models():
    """Test getting all available models."""
    manager = ModelManager()
    models = manager.get_available_models()

    assert isinstance(models, list)
    assert len(models) > 0


def test_get_available_models_with_capability():
    """Test filtering models by capability."""
    manager = ModelManager()
    models = manager.get_available_models(capability=ModelCapability.REASONING)

    assert isinstance(models, list)
    for model in models:
        assert ModelCapability.REASONING in model.capabilities


def test_gpu_status():
    """Test GPU status detection."""
    manager = ModelManager()
    status = manager.get_gpu_status()

    assert isinstance(status, dict)
    assert "available" in status


def test_model_recommendations():
    """Test model recommendations."""
    manager = ModelManager()
    recommendations = manager.get_model_recommendations("Write a Python script")

    assert isinstance(recommendations, list)
    if recommendations:
        model, reason = recommendations[0]
        assert model is not None
        assert isinstance(reason, str)
