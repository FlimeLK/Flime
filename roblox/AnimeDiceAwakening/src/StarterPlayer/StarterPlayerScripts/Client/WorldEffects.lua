-- WorldEffects: локальні ефекти світу на екрані цього гравця.
--  • вмикає/вимикає аури героїв і частинки оточення (пелюстки, іскри) за налаштуванням "Ефекти";
--  • плавно обертає моделі з тегом Spin (наприклад, гігантський кубик у лобі).
-- Змінюється лише на екрані цього гравця, інші гравці бачать свої налаштування.

local CollectionService = game:GetService("CollectionService")
local RunService = game:GetService("RunService")

local Client = script.Parent
local ClientState = require(Client:WaitForChild("ClientState"))

local WorldEffects = {}

local AURA_TAG = "HeroAura" -- той самий тег, що в HeroModelBuilder на сервері
local AMBIENT_TAG = "AmbientFx" -- той самий тег, що в BuildUtil на сервері
local SPIN_TAG = "Spin"

local spinning = {} -- [Model] = { base = CFrame, speed = град/с, bob = студів }

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
	for _, tag in { AURA_TAG, AMBIENT_TAG } do
		for _, instance in CollectionService:GetTagged(tag) do
			apply(instance)
		end
	end
end

local function addSpinner(model)
	if model:IsA("Model") then
		spinning[model] = {
			base = model:GetPivot(),
			speed = math.rad(model:GetAttribute("SpinSpeed") or 30),
			bob = model:GetAttribute("BobHeight") or 0,
		}
	end
end

function WorldEffects.Init()
	for _, tag in { AURA_TAG, AMBIENT_TAG } do
		CollectionService:GetInstanceAddedSignal(tag):Connect(apply)
	end
	ClientState.OnSettingChanged(function(key)
		if key == "effects" then
			applyAll()
		end
	end)
	applyAll()

	for _, model in CollectionService:GetTagged(SPIN_TAG) do
		addSpinner(model)
	end
	CollectionService:GetInstanceAddedSignal(SPIN_TAG):Connect(addSpinner)
	CollectionService:GetInstanceRemovedSignal(SPIN_TAG):Connect(function(model)
		spinning[model] = nil
	end)
	RunService.RenderStepped:Connect(function()
		local t = os.clock()
		for model, spin in spinning do
			if model.Parent then
				local position = spin.base.Position + Vector3.new(0, math.sin(t * 1.6) * spin.bob, 0)
				model:PivotTo(CFrame.new(position) * CFrame.Angles(0, t * spin.speed, 0) * spin.base.Rotation)
			else
				spinning[model] = nil
			end
		end
	end)
end

return WorldEffects
