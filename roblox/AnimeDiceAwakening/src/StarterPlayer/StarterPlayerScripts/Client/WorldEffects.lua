-- WorldEffects: локально вмикає/вимикає аури героїв за налаштуванням "Ефекти".
-- Змінюється лише на екрані цього гравця, інші гравці бачать свої налаштування.

local CollectionService = game:GetService("CollectionService")

local Client = script.Parent
local ClientState = require(Client:WaitForChild("ClientState"))

local WorldEffects = {}

local AURA_TAG = "HeroAura" -- той самий тег, що в HeroModelBuilder на сервері

local function effectsEnabled()
	-- Поки дані не прийшли, ефекти увімкнені
	return ClientState.Data == nil or ClientState.GetSetting("effects")
end

local function apply(instance)
	if instance:IsA("ParticleEmitter") or instance:IsA("Light") then
		instance.Enabled = effectsEnabled()
	end
end

local function applyAll()
	for _, instance in CollectionService:GetTagged(AURA_TAG) do
		apply(instance)
	end
end

function WorldEffects.Init()
	CollectionService:GetInstanceAddedSignal(AURA_TAG):Connect(apply)
	ClientState.OnSettingChanged(function(key)
		if key == "effects" then
			applyAll()
		end
	end)
	applyAll()
end

return WorldEffects
