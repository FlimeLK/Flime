-- Roblox API mocks for testing server logic in plain Luau (no Studio needed).
-- Run via: python3 tests/run_tests.py
local ROOT = G.ROOT

local function readFile(path)
	return assert(G.SOURCES[path], "no source " .. path)
end
G.readFile = readFile

-- Instances --------------------------------------------------------------
local InstanceMT = {}
local methods = {}

local function newInstance(className, name)
	local raw = { __props = { ClassName = className, Name = name or className }, __children = {}, __attrs = {} }
	return setmetatable(raw, InstanceMT)
end

InstanceMT.__index = function(self, key)
	local props = rawget(self, "__props")
	if props[key] ~= nil then
		return props[key]
	end
	if methods[key] then
		return methods[key]
	end
	for _, child in rawget(self, "__children") do
		if child.Name == key then
			return child
		end
	end
	if key == "Changed" or key == "Destroying" or key == "OnClientEvent" or key == "CharacterAdded" then
		local sig = { Connect = function() return { Disconnect = function() end } end }
		props[key] = sig
		return sig
	end
	return nil
end

InstanceMT.__newindex = function(self, key, value)
	local props = rawget(self, "__props")
	if key == "Parent" then
		local old = props.Parent
		if old then
			local list = rawget(old, "__children")
			for i, c in list do
				if c == self then
					table.remove(list, i)
					break
				end
			end
		end
		props.Parent = value
		if value then
			table.insert(rawget(value, "__children"), self)
		end
		return
	end
	props[key] = value
end

function methods.FindFirstChild(self, name)
	for _, child in rawget(self, "__children") do
		if child.Name == name then
			return child
		end
	end
	return nil
end
function methods.WaitForChild(self, name)
	return assert(methods.FindFirstChild(self, name), "WaitForChild failed: " .. tostring(name))
end
function methods.GetChildren(self)
	return table.clone(rawget(self, "__children"))
end
function methods.ClearAllChildren(self)
	for _, c in methods.GetChildren(self) do
		c.Parent = nil
	end
end
function methods.Destroy(self)
	self.Parent = nil
end
function methods.SetAttribute(self, k, v)
	rawget(self, "__attrs")[k] = v
end
function methods.GetAttribute(self, k)
	return rawget(self, "__attrs")[k]
end
function methods.IsA(self, c)
	return self.ClassName == c
end
function methods.FireClient(self, player, ...)
	table.insert(G.fired, { remote = self.Name, player = player, args = { ... } })
end
function methods.Kick(self, msg)
	G.kicked[self] = msg
end

-- Modules ------------------------------------------------------------------
local PRELUDE = "local script, game, workspace, Instance, Color3, Vector3, CFrame, Enum, UDim2, UDim, Vector2, task, Random, require, typeof, ColorSequence, NumberSequence, NumberSequenceKeypoint, NumberRange, os, warn = ...\n"

local cache = {}
local env = {}

local function makeModule(parent, name, path)
	local m = newInstance("ModuleScript", name)
	rawget(m, "__props").__path = path
	m.Parent = parent
	return m
end

local function folder(parent, name)
	local f = newInstance("Folder", name)
	f.Parent = parent
	return f
end

local function mockRequire(moduleScript)
	if cache[moduleScript] ~= nil then
		return cache[moduleScript]
	end
	local path = rawget(moduleScript, "__props").__path
	local src = readFile(path)
	local fn = assert(loadstring(PRELUDE .. src, path))
	local result = fn(moduleScript, env.game, env.workspace, env.Instance, env.Color3, env.Vector3, env.CFrame, env.Enum, env.UDim2, env.UDim, env.Vector2, env.task, env.Random, mockRequire, env.typeof, env.Color3, env.Color3, env.Color3, env.Color3, env.os, function(...) G.warnings = (G.warnings or 0) + 1 end)
	cache[moduleScript] = result
	return result
end

-- Values ------------------------------------------------------------------
local Color3 = {}
Color3.__index = Color3
function Color3.fromRGB(r, g, b)
	return setmetatable({ R = r / 255, G = g / 255, B = b / 255 }, Color3)
end
function Color3.new(r, g, b)
	return setmetatable({ R = r or 0, G = g or 0, B = b or 0 }, Color3)
end
function Color3:Lerp(o, a)
	return Color3.new(self.R + (o.R - self.R) * a, self.G + (o.G - self.G) * a, self.B + (o.B - self.B) * a)
end
setmetatable(Color3, { __call = function() return Color3.new() end })

local anyValue = setmetatable({}, {
	__index = function(t, k)
		return t
	end,
	__call = function(t)
		return t
	end,
	__mul = function(a)
		return a
	end,
})

-- Tasks ---------------------------------------------------------------------
G.deferred = {}
local task = {}
function task.spawn(f, ...)
	local co = coroutine.create(f)
	local ok, err = coroutine.resume(co, ...)
	if not ok then
		error(err)
	end
	return co
end
function task.defer(f, ...)
	table.insert(G.deferred, { f, ... })
end
function task.wait(t)
	if coroutine.isyieldable() then
		coroutine.yield()
	end
	return t
end
function task.delay() end
G.flushDeferred = function()
	local list = G.deferred
	G.deferred = {}
	for _, item in list do
		item[1](table.unpack(item, 2))
	end
end

-- Services ----------------------------------------------------------------
G.fired = {}
G.kicked = {}
G.datastore = {}
G.datastoreFail = 0

local function deepCopy(v)
	if type(v) ~= "table" then
		return v
	end
	local c = {}
	for k, x in v do
		c[k] = deepCopy(x)
	end
	return c
end
G.deepCopy = deepCopy

local store = {}
function store:UpdateAsync(key, fn)
	if G.datastoreFail > 0 then
		G.datastoreFail -= 1
		error("Simulated DataStore outage")
	end
	local new = fn(deepCopy(G.datastore[key]))
	if new ~= nil then
		G.datastore[key] = deepCopy(new)
	end
	return new
end

local services = {
	ReplicatedStorage = newInstance("ReplicatedStorage"),
	ServerScriptService = newInstance("ServerScriptService"),
	Players = newInstance("Players"),
	RunService = { IsServer = function() return true end, IsStudio = function() return G.isStudio == true end },
	DataStoreService = { GetDataStore = function() return store end },
	HttpService = { GenerateGUID = function() return "guid" end },
	CollectionService = { AddTag = function() end },
}
function services.Players:GetPlayers()
	return G.players or {}
end

local game = newInstance("DataModel")
rawget(game, "__props").JobId = "job-A"
function methods.GetService(self, name)
	return services[name]
end
function methods.BindToClose(self, fn)
	G.onClose = fn
end

local workspace = newInstance("Workspace")

env.game = game
env.workspace = workspace
env.Instance = { new = function(c) return newInstance(c) end }
env.Color3 = Color3
env.Vector3 = anyValue
env.CFrame = anyValue
env.Enum = anyValue
env.UDim2 = anyValue
env.UDim = anyValue
env.Vector2 = anyValue
env.task = task
G.clockOffset = 0
local realOs = os
env.os = setmetatable({ clock = function() return realOs.clock() + G.clockOffset end }, { __index = realOs })
env.Random = { new = function() return { NextNumber = function() return math.random() end } end }
env.typeof = function(v)
	return type(v)
end

-- Build tree ----------------------------------------------------------------
local RS = services.ReplicatedStorage
local shared = folder(RS, "Shared")
local config = folder(shared, "Config")
for _, n in { "RarityConfig", "DiceConfig", "HeroConfig", "EconomyConfig", "WorldConfig" } do
	makeModule(config, n, ROOT .. "ReplicatedStorage/Shared/Config/" .. n .. ".lua")
end
makeModule(shared, "GameMath", ROOT .. "ReplicatedStorage/Shared/GameMath.lua")
makeModule(shared, "Remotes", ROOT .. "ReplicatedStorage/Shared/Remotes.lua")

local servicesFolder = folder(services.ServerScriptService, "Services")
for _, n in { "RateLimiter", "DataService", "InventoryService", "RollService", "IncomeService", "UpgradeService", "SettingsService" } do
	makeModule(servicesFolder, n, ROOT .. "ServerScriptService/Services/" .. n .. ".lua")
end
-- PlotService / HeroModelBuilder are visual: stub them
local plotStub = makeModule(servicesFolder, "PlotService", "")
cache[plotStub] = { RefreshPlot = function() end, AssignPlot = function() return true end, ReleasePlot = function() end }

G.Sim = {
	require = mockRequire,
	RS = RS,
	Services = servicesFolder,
	newPlayer = function(userId, name)
		local p = newInstance("Player", name)
		rawget(p, "__props").UserId = userId
		rawget(p, "__props").DisplayName = name
		p.Parent = services.Players
		return p
	end,
	game = game,
}

