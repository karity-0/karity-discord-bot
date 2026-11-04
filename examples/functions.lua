local function greeting(name)
    return "Hello, " .. name .. "!"
end

local names = {"Karity", "Discord"}
for i = 1, #names do
    print(greeting(names[i]))
end
