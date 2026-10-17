-- Виконує серверні будівельники карти (PlotService, WorldService, моделі героїв і ворогів)
-- поза Roblox і друкує JSON зі всіма деталями — для 3D-прев'ю (tools/preview/render.mjs).
-- Запуск: python3 tools/preview/export_scene.py > scene.json
local SOURCES = G.SOURCES
local ROOT = G.ROOT

-- Vector3 -----------------------------------------------------------------------
local Vector3 = {}
local V3 = {}
local function v3(x, y, z)
	return setmetatable({ X = x or 0, Y = y or 0, Z = z or 0 }, V3)
end
V3.__index = function(v, key)
	if key == "Magnitude" then
		return math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)
	elseif key == "Unit" then
		local m = math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)
		if m == 0 then
			return v3(0, 0, 0)
		end
		return v3(v.X / m, v.Y / m, v.Z / m)
	end
	return V3[key]
end
V3.__add = function(a, b)
	return v3(a.X + b.X, a.Y + b.Y, a.Z + b.Z)
end
V3.__sub = function(a, b)
	return v3(a.X - b.X, a.Y - b.Y, a.Z - b.Z)
end
V3.__unm = function(a)
	return v3(-a.X, -a.Y, -a.Z)
end
V3.__mul = function(a, b)
	if type(a) == "number" then
		return v3(b.X * a, b.Y * a, b.Z * a)
	elseif type(b) == "number" then
		return v3(a.X * b, a.Y * b, a.Z * b)
	end
	return v3(a.X * b.X, a.Y * b.Y, a.Z * b.Z)
end
V3.__div = function(a, b)
	if type(b) == "number" then
		return v3(a.X / b, a.Y / b, a.Z / b)
	end
	return v3(a.X / b.X, a.Y / b.Y, a.Z / b.Z)
end
V3.__eq = function(a, b)
	return a.X == b.X and a.Y == b.Y and a.Z == b.Z
end
function V3.Dot(a, b)
	return a.X * b.X + a.Y * b.Y + a.Z * b.Z
end
function V3.Cross(a, b)
	return v3(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X)
end
function V3.Lerp(a, b, t)
	return a + (b - a) * t
end
function V3.Max(a, b)
	return v3(math.max(a.X, b.X), math.max(a.Y, b.Y), math.max(a.Z, b.Z))
end
function V3.Min(a, b)
	return v3(math.min(a.X, b.X), math.min(a.Y, b.Y), math.min(a.Z, b.Z))
end
function V3.Abs(a)
	return v3(math.abs(a.X), math.abs(a.Y), math.abs(a.Z))
end
Vector3.new = v3
Vector3.zero = v3(0, 0, 0)
Vector3.one = v3(1, 1, 1)
Vector3.xAxis = v3(1, 0, 0)
Vector3.yAxis = v3(0, 1, 0)
Vector3.zAxis = v3(0, 0, 1)

-- CFrame (м — 3×3 по рядках; стовпці = Right, Up, Back) ---------------------------------
local CFrame = {}
local CF = {}
local function cf(px, py, pz, m)
	return setmetatable({ p = v3(px, py, pz), m = m or { 1, 0, 0, 0, 1, 0, 0, 0, 1 } }, CF)
end
local function mulMat(a, b)
	local r = {}
	for i = 0, 2 do
		for j = 0, 2 do
			r[i * 3 + j + 1] = a[i * 3 + 1] * b[j + 1] + a[i * 3 + 2] * b[3 + j + 1] + a[i * 3 + 3] * b[6 + j + 1]
		end
	end
	return r
end
local function mulVec(m, v)
	return v3(m[1] * v.X + m[2] * v.Y + m[3] * v.Z, m[4] * v.X + m[5] * v.Y + m[6] * v.Z, m[7] * v.X + m[8] * v.Y + m[9] * v.Z)
end
local function transpose(m)
	return { m[1], m[4], m[7], m[2], m[5], m[8], m[3], m[6], m[9] }
end
CF.__index = function(c, key)
	if key == "Position" then
		return c.p
	elseif key == "X" then
		return c.p.X
	elseif key == "Y" then
		return c.p.Y
	elseif key == "Z" then
		return c.p.Z
	elseif key == "RightVector" then
		return v3(c.m[1], c.m[4], c.m[7])
	elseif key == "UpVector" then
		return v3(c.m[2], c.m[5], c.m[8])
	elseif key == "LookVector" then
		return v3(-c.m[3], -c.m[6], -c.m[9])
	elseif key == "Rotation" then
		return cf(0, 0, 0, c.m)
	end
	return CF[key]
end
CF.__mul = function(a, b)
	if getmetatable(b) == CF then
		local p = mulVec(a.m, b.p) + a.p
		return cf(p.X, p.Y, p.Z, mulMat(a.m, b.m))
	end
	return mulVec(a.m, b) + a.p
end
CF.__add = function(a, v)
	return cf(a.p.X + v.X, a.p.Y + v.Y, a.p.Z + v.Z, a.m)
end
CF.__sub = function(a, v)
	return cf(a.p.X - v.X, a.p.Y - v.Y, a.p.Z - v.Z, a.m)
end
function CF.Inverse(c)
	local t = transpose(c.m)
	local p = -mulVec(t, c.p)
	return cf(p.X, p.Y, p.Z, t)
end
function CF.ToWorldSpace(a, b)
	return a * b
end
function CF.ToObjectSpace(a, b)
	return a:Inverse() * b
end
function CF.PointToWorldSpace(a, v)
	return a * v
end
function CF.PointToObjectSpace(a, v)
	return a:Inverse() * v
end
function CF.VectorToWorldSpace(a, v)
	return mulVec(a.m, v)
end
function CF.VectorToObjectSpace(a, v)
	return mulVec(transpose(a.m), v)
end
function CF.Lerp(a, b, t)
	local p = a.p:Lerp(b.p, t)
	return cf(p.X, p.Y, p.Z, if t < 0.5 then a.m else b.m)
end
function CF.GetComponents(c)
	local m = c.m
	return c.p.X, c.p.Y, c.p.Z, m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9]
end
local function rx(a)
	local c, s = math.cos(a), math.sin(a)
	return { 1, 0, 0, 0, c, -s, 0, s, c }
end
local function ry(a)
	local c, s = math.cos(a), math.sin(a)
	return { c, 0, s, 0, 1, 0, -s, 0, c }
end
local function rz(a)
	local c, s = math.cos(a), math.sin(a)
	return { c, -s, 0, s, c, 0, 0, 0, 1 }
end
local function lookAt(at, target, up)
	up = up or v3(0, 1, 0)
	local look = (target - at).Unit
	local right = look:Cross(up)
	if right.Magnitude < 1e-6 then
		right = look:Cross(v3(0, 0, 1))
	end
	right = right.Unit
	local up2 = right:Cross(look)
	return cf(at.X, at.Y, at.Z, { right.X, up2.X, -look.X, right.Y, up2.Y, -look.Y, right.Z, up2.Z, -look.Z })
end
function CFrame.new(a, b, c, ...)
	if a == nil then
		return cf(0, 0, 0)
	elseif type(a) == "table" then
		if b then
			return lookAt(a, b)
		end
		return cf(a.X, a.Y, a.Z)
	end
	local rest = { ... }
	if #rest == 9 then
		return cf(a, b, c, rest)
	end
	return cf(a, b, c)
end
function CFrame.Angles(x, y, z)
	return cf(0, 0, 0, mulMat(mulMat(rx(x or 0), ry(y or 0)), rz(z or 0)))
end
CFrame.fromEulerAnglesXYZ = CFrame.Angles
function CFrame.fromEulerAnglesYXZ(x, y, z)
	return cf(0, 0, 0, mulMat(mulMat(ry(y or 0), rx(x or 0)), rz(z or 0)))
end
CFrame.fromOrientation = CFrame.fromEulerAnglesYXZ
function CFrame.fromAxisAngle(axis, angle)
	local u = axis.Unit
	local c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
	return cf(0, 0, 0, {
		t * u.X * u.X + c, t * u.X * u.Y - s * u.Z, t * u.X * u.Z + s * u.Y,
		t * u.X * u.Y + s * u.Z, t * u.Y * u.Y + c, t * u.Y * u.Z - s * u.X,
		t * u.X * u.Z - s * u.Y, t * u.Y * u.Z + s * u.X, t * u.Z * u.Z + c,
	})
end
CFrame.lookAt = lookAt
CFrame.identity = cf(0, 0, 0)

-- Color3 ----------------------------------------------------------------------------------
local Color3 = {}
local C3 = {}
C3.__index = C3
local function c3(r, g, b)
	return setmetatable({ R = r or 0, G = g or 0, B = b or 0 }, C3)
end
function Color3.new(r, g, b)
	return c3(r, g, b)
end
function Color3.fromRGB(r, g, b)
	return c3((r or 0) / 255, (g or 0) / 255, (b or 0) / 255)
end
function Color3.fromHSV(h, s, v)
	local i = math.floor(h * 6)
	local f = h * 6 - i
	local p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
	i %= 6
	if i == 0 then
		return c3(v, t, p)
	elseif i == 1 then
		return c3(q, v, p)
	elseif i == 2 then
		return c3(p, v, t)
	elseif i == 3 then
		return c3(p, q, v)
	elseif i == 4 then
		return c3(t, p, v)
	end
	return c3(v, p, q)
end
function C3.Lerp(a, b, t)
	return c3(a.R + (b.R - a.R) * t, a.G + (b.G - a.G) * t, a.B + (b.B - a.B) * t)
end
function C3.ToHSV(c)
	local max, min = math.max(c.R, c.G, c.B), math.min(c.R, c.G, c.B)
	local d = max - min
	local h = 0
	if d > 0 then
		if max == c.R then
			h = ((c.G - c.B) / d) % 6
		elseif max == c.G then
			h = (c.B - c.R) / d + 2
		else
			h = (c.R - c.G) / d + 4
		end
		h /= 6
	end
	return h, if max > 0 then d / max else 0, max
end

-- Enum: Enum.Material.Neon → унікальний об'єкт із Name ------------------------------------------
local enumCache = {}
local Enum = setmetatable({}, {
	__index = function(_, enumType)
		enumCache[enumType] = enumCache[enumType] or setmetatable({}, {
			__index = function(t, name)
				local item = { Name = name, EnumType = enumType }
				rawset(t, name, item)
				return item
			end,
		})
		return enumCache[enumType]
	end,
})

-- Будь-які інші типи (UDim2, NumberSequence, TweenInfo...) — заглушки
local function struct(...)
	return { ... }
end
local function ctor()
	return setmetatable({ new = struct, fromScale = struct, fromOffset = struct }, {
		__call = function(_, ...)
			return struct(...)
		end,
	})
end

-- Signals ------------------------------------------------------------------------------------
local function signal()
	return {
		Connect = function()
			return { Disconnect = function() end }
		end,
		Once = function()
			return { Disconnect = function() end }
		end,
		Wait = function() end,
	}
end

-- Instances ----------------------------------------------------------------------------------
local PARENT_CLASSES = {
	Part = { "BasePart", "PVInstance" },
	WedgePart = { "BasePart", "PVInstance" },
	CornerWedgePart = { "BasePart", "PVInstance" },
	TrussPart = { "BasePart", "PVInstance" },
	SpawnLocation = { "Part", "BasePart", "PVInstance" },
	MeshPart = { "BasePart", "PVInstance" },
	Model = { "PVInstance" },
	PointLight = { "Light" },
	SpotLight = { "Light" },
	SurfaceLight = { "Light" },
	Script = { "BaseScript", "LuaSourceContainer" },
	LocalScript = { "BaseScript", "LuaSourceContainer" },
	ModuleScript = { "LuaSourceContainer" },
}
local BASE_PART = { Part = true, WedgePart = true, CornerWedgePart = true, TrussPart = true, SpawnLocation = true, MeshPart = true }
local EVENTS = {
	Changed = true, Destroying = true, Touched = true, TouchEnded = true, ChildAdded = true, ChildRemoved = true,
	DescendantAdded = true, CharacterAdded = true, CharacterRemoving = true, MouseClick = true, Triggered = true,
	PlayerAdded = true, PlayerRemoving = true, Heartbeat = true, RenderStepped = true, Stepped = true, OnServerEvent = true,
	OnClientEvent = true, Died = true, AncestryChanged = true,
}

local Inst = {}
local methods = {}
local nextId = 0

local function isA(className, query)
	if className == query or query == "Instance" then
		return true
	end
	for _, parentClass in PARENT_CLASSES[className] or {} do
		if parentClass == query then
			return true
		end
	end
	return false
end

local function newInstance(className, name)
	nextId += 1
	local props = { ClassName = className, Name = name or className }
	if BASE_PART[className] then
		props.Size = v3(4, 1, 2)
		props.CFrame = cf(0, 0, 0)
		props.Color = Color3.fromRGB(163, 162, 165)
		props.Transparency = 0
		props.Material = Enum.Material.Plastic
		props.Shape = Enum.PartType.Block
		props.PivotOffset = cf(0, 0, 0)
		props.Anchored = false
		props.CanCollide = true
	elseif className == "Model" then
		props.__scale = 1
	end
	return setmetatable({ __id = nextId, __props = props, __children = {}, __attrs = {}, __tags = {}, __signals = {} }, Inst)
end

Inst.__index = function(self, key)
	local props = rawget(self, "__props")
	if key == "Position" and props.CFrame then
		return props.CFrame.p
	elseif key == "Orientation" and props.CFrame then
		return v3(0, 0, 0)
	end
	local value = props[key]
	if value ~= nil then
		return value
	end
	if methods[key] then
		return methods[key]
	end
	if EVENTS[key] then
		local signals = rawget(self, "__signals")
		signals[key] = signals[key] or signal()
		return signals[key]
	end
	for _, child in rawget(self, "__children") do
		if child.Name == key then
			return child
		end
	end
	return nil
end

Inst.__newindex = function(self, key, value)
	local props = rawget(self, "__props")
	if key == "Parent" then
		local old = props.Parent
		if old then
			local list = rawget(old, "__children")
			for i, child in list do
				if child == self then
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
	elseif key == "Position" and props.CFrame then
		local c = props.CFrame
		props.CFrame = cf(value.X, value.Y, value.Z, c.m)
		return
	end
	props[key] = value
end
Inst.__tostring = function(self)
	return rawget(self, "__props").Name
end

function methods.FindFirstChild(self, name, recursive)
	for _, child in rawget(self, "__children") do
		if child.Name == name then
			return child
		end
	end
	if recursive then
		for _, child in rawget(self, "__children") do
			local found = child:FindFirstChild(name, true)
			if found then
				return found
			end
		end
	end
	return nil
end
function methods.WaitForChild(self, name)
	return assert(self:FindFirstChild(name), "WaitForChild: " .. tostring(name))
end
function methods.FindFirstChildOfClass(self, className)
	for _, child in rawget(self, "__children") do
		if child.ClassName == className then
			return child
		end
	end
	return nil
end
function methods.FindFirstChildWhichIsA(self, className, recursive)
	for _, child in (if recursive then self:GetDescendants() else rawget(self, "__children")) do
		if child:IsA(className) then
			return child
		end
	end
	return nil
end
function methods.FindFirstAncestorWhichIsA(self, className)
	local parent = self.Parent
	while parent do
		if parent:IsA(className) then
			return parent
		end
		parent = parent.Parent
	end
	return nil
end
function methods.GetChildren(self)
	return table.clone(rawget(self, "__children"))
end
function methods.GetDescendants(self)
	local out = {}
	local function walk(node)
		for _, child in rawget(node, "__children") do
			table.insert(out, child)
			walk(child)
		end
	end
	walk(self)
	return out
end
function methods.IsA(self, className)
	return isA(self.ClassName, className)
end
function methods.IsDescendantOf(self, ancestor)
	local parent = self.Parent
	while parent do
		if parent == ancestor then
			return true
		end
		parent = parent.Parent
	end
	return false
end
function methods.Destroy(self)
	self.Parent = nil
end
function methods.ClearAllChildren(self)
	for _, child in self:GetChildren() do
		child.Parent = nil
	end
end
function methods.Clone(self)
	local copy = newInstance(self.ClassName)
	for key, value in rawget(self, "__props") do
		if key ~= "Parent" then
			rawget(copy, "__props")[key] = value
		end
	end
	for key, value in rawget(self, "__attrs") do
		rawget(copy, "__attrs")[key] = value
	end
	for _, child in rawget(self, "__children") do
		child:Clone().Parent = copy
	end
	return copy
end
function methods.SetAttribute(self, key, value)
	rawget(self, "__attrs")[key] = value
end
function methods.GetAttribute(self, key)
	return rawget(self, "__attrs")[key]
end
function methods.GetAttributeChangedSignal()
	return signal()
end
function methods.GetPropertyChangedSignal()
	return signal()
end

local function partsOf(model)
	local parts = {}
	for _, d in model:GetDescendants() do
		if d:IsA("BasePart") then
			table.insert(parts, d)
		end
	end
	return parts
end
local function boundingBox(parts)
	local lo, hi = v3(math.huge, math.huge, math.huge), v3(-math.huge, -math.huge, -math.huge)
	for _, part in parts do
		local c, s = part.CFrame, part.Size / 2
		for _, sx in { -1, 1 } do
			for _, sy in { -1, 1 } do
				for _, sz in { -1, 1 } do
					local corner = c * v3(s.X * sx, s.Y * sy, s.Z * sz)
					lo, hi = lo:Min(corner), hi:Max(corner)
				end
			end
		end
	end
	if lo.X == math.huge then
		return cf(0, 0, 0), v3(0, 0, 0)
	end
	local center = (lo + hi) / 2
	return cf(center.X, center.Y, center.Z), hi - lo
end
function methods.GetBoundingBox(self)
	return boundingBox(partsOf(self))
end
function methods.GetExtentsSize(self)
	local _, size = boundingBox(partsOf(self))
	return size
end
function methods.GetPivot(self)
	if self:IsA("BasePart") then
		return self.CFrame * self.PivotOffset
	end
	local primary = self.PrimaryPart
	if primary then
		return primary.CFrame * primary.PivotOffset
	end
	local props = rawget(self, "__props")
	if not props.WorldPivot then
		props.WorldPivot = (boundingBox(partsOf(self)))
	end
	return props.WorldPivot
end
function methods.PivotTo(self, target)
	if self:IsA("BasePart") then
		self.CFrame = target * self.PivotOffset:Inverse()
		return
	end
	local delta = target * self:GetPivot():Inverse()
	for _, part in partsOf(self) do
		part.CFrame = delta * part.CFrame
	end
	if not self.PrimaryPart then
		rawget(self, "__props").WorldPivot = target
	end
end
function methods.GetScale(self)
	return rawget(self, "__props").__scale or 1
end
function methods.ScaleTo(self, scale)
	local factor = scale / self:GetScale()
	local pivot = self:GetPivot()
	for _, part in partsOf(self) do
		local local_ = pivot:Inverse() * part.CFrame
		local p = local_.p * factor
		part.CFrame = pivot * cf(p.X, p.Y, p.Z, local_.m)
		part.Size = part.Size * factor
	end
	rawget(self, "__props").__scale = scale
end
function methods.GetPlayers()
	return {}
end
function methods.GetPlayerFromCharacter()
	return nil
end
function methods.Kick() end

-- Terrain: запам'ятовуємо заливки для прев'ю
local terrainFills = {}
function methods.FillBlock(self, cframe, size, material)
	table.insert(terrainFills, { shape = "Block", cframe = cframe, size = size, material = material.Name })
end
function methods.FillBall(self, center, radius, material)
	table.insert(terrainFills, { shape = "Ball", cframe = cf(center.X, center.Y, center.Z), size = v3(radius * 2, radius * 2, radius * 2), material = material.Name })
end
function methods.FillCylinder(self, cframe, height, radius, material)
	table.insert(terrainFills, { shape = "Cylinder", cframe = cframe, size = v3(radius * 2, height, radius * 2), material = material.Name })
end
function methods.Clear() end

-- Services ----------------------------------------------------------------------------------
local game = newInstance("DataModel", "Game")
local workspace = newInstance("Workspace", "Workspace")
workspace.Parent = game
local terrain = newInstance("Terrain", "Terrain")
terrain.Parent = workspace

local tagged = {}
local services = {
	Workspace = workspace,
	ReplicatedStorage = newInstance("ReplicatedStorage", "ReplicatedStorage"),
	ServerScriptService = newInstance("ServerScriptService", "ServerScriptService"),
	Players = newInstance("Players", "Players"),
	Lighting = newInstance("Lighting", "Lighting"),
	CollectionService = {
		AddTag = function(_, instance, tag)
			rawget(instance, "__tags")[tag] = true
			tagged[tag] = tagged[tag] or {}
			table.insert(tagged[tag], instance)
		end,
		HasTag = function(_, instance, tag)
			return rawget(instance, "__tags")[tag] == true
		end,
		GetTagged = function(_, tag)
			return tagged[tag] or {}
		end,
		GetInstanceAddedSignal = signal,
		GetInstanceRemovedSignal = signal,
	},
	RunService = {
		IsStudio = function()
			return false
		end,
		IsServer = function()
			return true
		end,
		IsClient = function()
			return false
		end,
		Heartbeat = signal(),
		Stepped = signal(),
	},
	TweenService = {
		Create = function()
			return { Play = function() end, Cancel = function() end, Completed = signal() }
		end,
	},
	HttpService = {
		GenerateGUID = function()
			return "guid"
		end,
		JSONEncode = function()
			return "{}"
		end,
	},
	Debris = { AddItem = function() end },
}
function methods.GetService(_, name)
	return services[name] or newInstance(name, name)
end
function methods.BindToClose() end

-- Modules ------------------------------------------------------------------------------------
local GLOBALS = {
	"script", "game", "workspace", "Instance", "Color3", "Vector3", "CFrame", "Enum", "UDim2", "UDim", "Vector2",
	"task", "Random", "require", "typeof", "ColorSequence", "ColorSequenceKeypoint", "NumberSequence",
	"NumberSequenceKeypoint", "NumberRange", "TweenInfo", "os", "warn", "tick", "Rect", "Font", "PhysicalProperties",
	"BrickColor", "Ray", "RaycastParams", "OverlapParams",
}
local PRELUDE = "local " .. table.concat(GLOBALS, ", ") .. " = ...\n"

local cache = {}
local env = {
	game = game,
	workspace = workspace,
	Instance = {
		new = function(className, parent)
			local instance = newInstance(className)
			if parent then
				instance.Parent = parent
			end
			return instance
		end,
	},
	Color3 = Color3,
	Vector3 = Vector3,
	CFrame = CFrame,
	Enum = Enum,
	UDim2 = ctor(),
	UDim = ctor(),
	Vector2 = ctor(),
	task = {
		spawn = function(f, ...)
			local co = coroutine.create(f)
			coroutine.resume(co, ...)
			return co
		end,
		defer = function() end,
		delay = function() end,
		wait = function(t)
			return t
		end,
	},
	Random = {
		new = function(seed)
			local state = seed or 1
			local function nextNumber()
				state = (state * 1103515245 + 12345) % 2147483648
				return state / 2147483648
			end
			return {
				NextNumber = function(_, lo, hi)
					lo, hi = lo or 0, hi or 1
					return lo + (hi - lo) * nextNumber()
				end,
				NextInteger = function(_, lo, hi)
					return lo + math.floor(nextNumber() * (hi - lo + 1))
				end,
			}
		end,
	},
	typeof = function(value)
		local mt = getmetatable(value)
		if mt == V3 then
			return "Vector3"
		elseif mt == CF then
			return "CFrame"
		elseif mt == C3 then
			return "Color3"
		elseif mt == Inst then
			return "Instance"
		end
		return type(value)
	end,
	ColorSequence = ctor(),
	ColorSequenceKeypoint = ctor(),
	NumberSequence = ctor(),
	NumberSequenceKeypoint = ctor(),
	NumberRange = ctor(),
	TweenInfo = ctor(),
	os = os,
	warn = function() end,
	tick = os.clock,
	Rect = ctor(),
	Font = ctor(),
	PhysicalProperties = ctor(),
	BrickColor = ctor(),
	Ray = ctor(),
	RaycastParams = ctor(),
	OverlapParams = ctor(),
}

local function mockRequire(moduleScript)
	if cache[moduleScript] ~= nil then
		return cache[moduleScript]
	end
	local path = rawget(moduleScript, "__props").__path
	local fn = assert(loadstring(PRELUDE .. assert(SOURCES[path], "no source " .. tostring(path)), path))
	local args = {}
	for i, name in GLOBALS do
		args[i] = if name == "script" then moduleScript elseif name == "require" then mockRequire else env[name]
	end
	local result = fn(table.unpack(args, 1, #GLOBALS))
	cache[moduleScript] = result
	return result
end

local function folder(parent, name)
	local f = newInstance("Folder", name)
	f.Parent = parent
	return f
end
local function module(parent, name, path, stub)
	local m = newInstance("ModuleScript", name)
	rawget(m, "__props").__path = path
	m.Parent = parent
	if stub then
		cache[m] = stub
	end
	return m
end

local RS = services.ReplicatedStorage
local shared = folder(RS, "Shared")
local config = folder(shared, "Config")
for _, name in { "RarityConfig", "DiceConfig", "HeroConfig", "EconomyConfig", "WorldConfig", "CombatConfig", "EnemyConfig", "QuestConfig", "ShopConfig", "AssetConfig" } do
	module(config, name, ROOT .. "ReplicatedStorage/Shared/Config/" .. name .. ".lua")
end
module(shared, "GameMath", ROOT .. "ReplicatedStorage/Shared/GameMath.lua")
module(shared, "HeroModelBuilder", ROOT .. "ReplicatedStorage/Shared/HeroModelBuilder.lua")
module(shared, "Remotes", "", { Handle = function() end, Notify = function() end, Get = function() end })
folder(RS, "HeroModels")

local servicesFolder = folder(services.ServerScriptService, "Services")
for _, name in { "BuildUtil", "PlotService", "WorldService", "EnemyModelBuilder" } do
	module(servicesFolder, name, ROOT .. "ServerScriptService/Services/" .. name .. ".lua")
end

-- Гравець-приклад: 8 відкритих слотів з героями різної рідкості
local PREVIEW_HEROES = { "riku_windstep", "hana_emberling", "shiro_quickblade", "akane_crimsonfan", "seren_starblade", "astra_novaempress", "solenne_eclipse" }
local previewData = { slotCount = 8, slots = {}, heroes = {}, incomeLevel = 0, rebirths = 0 }
for i, heroId in PREVIEW_HEROES do
	local uid = "h" .. i
	previewData.heroes[uid] = { id = heroId, level = 5, awakened = i == 7 }
	previewData.slots[i] = uid
end
for i = #PREVIEW_HEROES + 1, 12 do
	previewData.slots[i] = ""
end
module(servicesFolder, "DataService", "", {
	Get = function()
		return previewData
	end,
})
module(servicesFolder, "CombatService", "", { ClearTarget = function() end })
module(servicesFolder, "RateLimiter", "", {
	new = function()
		return { Check = function() return true end }
	end,
})
local EnemyModelBuilder = mockRequire(servicesFolder.EnemyModelBuilder)
local EnemyConfig = mockRequire(config.EnemyConfig)
module(servicesFolder, "EnemyService", "", {
	SpawnWorldEnemies = function(worldId, center, parent)
		for _, spawnInfo in EnemyConfig.WorldSpawns[worldId] or {} do
			local model = EnemyModelBuilder.Build(EnemyConfig.Enemies[spawnInfo.enemy])
			model:PivotTo(center * CFrame.new(spawnInfo.offset) * CFrame.Angles(0, math.pi, 0))
			model.Parent = parent
		end
	end,
})

-- Будуємо карту --------------------------------------------------------------------------------
local PlotService = mockRequire(servicesFolder.PlotService)
local WorldService = mockRequire(servicesFolder.WorldService)
PlotService.Init()
local player = newInstance("Player", "Preview")
rawget(player, "__props").UserId = 1
rawget(player, "__props").DisplayName = "Preview"
PlotService.AssignPlot(player)
WorldService.Init()

-- JSON ------------------------------------------------------------------------------------------
local function num(x)
	local text = string.format("%.3f", x):gsub("0+$", ""):gsub("%.$", "")
	return if text == "-0" then "0" else text
end
local function str(s)
	s = s:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\t", " ")
	return '"' .. s .. '"'
end
local function cframeJson(c)
	local parts = {}
	for _, value in { c:GetComponents() } do
		table.insert(parts, num(value))
	end
	return "[" .. table.concat(parts, ",") .. "]"
end
local function vecJson(v)
	return "[" .. num(v.X) .. "," .. num(v.Y) .. "," .. num(v.Z) .. "]"
end
local function colorJson(c)
	return "[" .. num(c.R) .. "," .. num(c.G) .. "," .. num(c.B) .. "]"
end

local partsOut, lightsOut, textsOut, particlesOut = {}, {}, {}, {}
for _, d in workspace:GetDescendants() do
	if d:IsA("BasePart") then
		if d.Transparency < 1 then
			local tags = {}
			for tag in rawget(d, "__tags") do
				table.insert(tags, str(tag))
			end
			table.insert(partsOut, ("{\"c\":%s,\"s\":%s,\"sz\":%s,\"cf\":%s,\"col\":%s,\"m\":%s,\"t\":%s,\"tags\":[%s]}"):format(
				str(d.ClassName), str(d.Shape.Name), vecJson(d.Size), cframeJson(d.CFrame), colorJson(d.Color), str(d.Material.Name), num(d.Transparency), table.concat(tags, ",")
			))
		end
		for _, child in d:GetChildren() do
			if child:IsA("Light") and child.Enabled ~= false then
				table.insert(lightsOut, ("{\"p\":%s,\"col\":%s,\"r\":%s,\"b\":%s}"):format(vecJson(d.Position), colorJson(child.Color or Color3.new(1, 1, 1)), num(child.Range or 8), num(child.Brightness or 1)))
			elseif child.ClassName == "SurfaceGui" then
				local label = child:FindFirstChildWhichIsA("TextLabel")
				if label and label.Text and label.Text ~= "" then
					table.insert(textsOut, ("{\"cf\":%s,\"sz\":%s,\"face\":%s,\"text\":%s,\"col\":%s}"):format(cframeJson(d.CFrame), vecJson(d.Size), str((child.Face or Enum.NormalId.Front).Name), str(label.Text), colorJson(label.TextColor3 or Color3.new(1, 1, 1))))
				end
			elseif child.ClassName == "ParticleEmitter" then
				local color = Color3.new(1, 1, 1)
				table.insert(particlesOut, ("{\"cf\":%s,\"sz\":%s,\"col\":%s,\"rate\":%s}"):format(cframeJson(d.CFrame), vecJson(d.Size), colorJson(color), num(child.Rate or 5)))
			end
		end
	end
end
local terrainOut = {}
for _, fill in terrainFills do
	table.insert(terrainOut, ("{\"s\":%s,\"cf\":%s,\"sz\":%s,\"m\":%s}"):format(str(fill.shape), cframeJson(fill.cframe), vecJson(fill.size), str(fill.material)))
end
print(("{\"parts\":[%s],\"lights\":[%s],\"texts\":[%s],\"particles\":[%s],\"terrain\":[%s]}"):format(
	table.concat(partsOut, ","), table.concat(lightsOut, ","), table.concat(textsOut, ","), table.concat(particlesOut, ","), table.concat(terrainOut, ",")
))
