-- Leader key
vim.g.mapleader = " "
vim.g.maplocalleader = " "

-- Line numbers
vim.opt.number = true
vim.opt.relativenumber = true

-- Scrolling / cursor
vim.opt.scrolloff = 999
vim.opt.sidescrolloff = 8

-- Indentation
vim.opt.expandtab = true
vim.opt.shiftwidth = 4
vim.opt.tabstop = 4
vim.opt.softtabstop = 4
vim.opt.smartindent = true

-- Search
vim.opt.ignorecase = true
vim.opt.smartcase = true
vim.opt.hlsearch = false
vim.opt.incsearch = true

-- Mouse / clipboard
vim.opt.mouse = "a"
vim.opt.clipboard = "unnamedplus"

-- Splits
vim.opt.splitbelow = true
vim.opt.splitright = true

-- Files: persistent undo, no swap/backup clutter
vim.opt.undofile = true
vim.opt.swapfile = false
vim.opt.backup = false
vim.opt.confirm = true

-- Timing
vim.opt.updatetime = 250
vim.opt.timeoutlen = 300

-- UI
vim.opt.termguicolors = true
vim.opt.signcolumn = "yes"
vim.opt.wrap = false
vim.opt.cursorline = true
vim.opt.laststatus = 3           -- single global statusline across splits
vim.opt.colorcolumn = "80"       -- visual ruler
vim.opt.pumheight = 10           -- cap completion popup height
vim.opt.completeopt = "menuone,noselect"
vim.opt.inccommand = "split"     -- live preview of :substitute & friends
vim.opt.virtualedit = "block"    -- free cursor movement in visual-block mode

vim.opt.foldmethod = "expr"
vim.opt.foldexpr = "v:lua.vim.treesitter.foldexpr()"
vim.opt.foldlevelstart = 99

-- Whitespace display
vim.opt.list = true
vim.opt.listchars = {
    tab = "Â» ",
    trail = "Â·",
    nbsp = "â£",
}

-- Keymaps

-- Esc removes search highlight
vim.keymap.set("n", "<Esc>", "<cmd>nohlsearch<CR>")

-- Move between split windows
vim.keymap.set("n", "<C-h>", "<C-w>h")
vim.keymap.set("n", "<C-j>", "<C-w>j")
vim.keymap.set("n", "<C-k>", "<C-w>k")
vim.keymap.set("n", "<C-l>", "<C-w>l")

-- Save / Quit
vim.keymap.set("n", "<leader>w", "<cmd>w<CR>")
vim.keymap.set("n", "<leader>q", "<cmd>q<CR>")
vim.keymap.set("n", "<leader>x", "<cmd>bdelete<CR>") -- close current buffer
vim.keymap.set("n", "<leader>h", "<cmd>split<CR>")   -- horizontal split
vim.keymap.set("n", "<leader>v", "<cmd>vsplit<CR>")  -- vertical split

-- Move selected lines up/down and re-indent
vim.keymap.set("v", "J", ":m '>+1<CR>gv=gv")
vim.keymap.set("v", "K", ":m '<-2<CR>gv=gv")

-- Stay in visual mode while indenting
vim.keymap.set("v", "<", "<gv")
vim.keymap.set("v", ">", ">gv")

-- Paste over a selection without clobbering your yank register
vim.keymap.set("x", "<leader>p", [["_dP]])

-- Delete to the void register (don't overwrite the clipboard)
vim.keymap.set({ "n", "v" }, "<leader>d", [["_d]])

-- Cycle buffers
vim.keymap.set("n", "<S-h>", "<cmd>bprevious<CR>")
vim.keymap.set("n", "<S-l>", "<cmd>bnext<CR>")

-- Plugins (built-in manager)
vim.pack.add({
    { src = "https://github.com/nvim-tree/nvim-web-devicons" },
    { src = "https://github.com/catppuccin/nvim", name = "catppuccin" },
    { src = "https://github.com/nvim-lualine/lualine.nvim" },
    { src = "https://github.com/ibhagwan/fzf-lua" },
    { src = "https://github.com/stevearc/oil.nvim" },
    { src = "https://github.com/goolord/alpha-nvim" },
    { src = "https://github.com/neovim/nvim-lspconfig" },
})

-- Colorscheme
local ok, catppuccin = pcall(require, "catppuccin")
if ok then
    catppuccin.setup({
        flavour = "mocha",
        -- Black background instead of mocha's default (#1e1e2e):
        -- color_overrides = { mocha = { base = "#000000", mantle = "#000000", crust = "#000000" } },
    })
    vim.cmd.colorscheme("catppuccin")
end

-- Statusline
require("lualine").setup({
    options = {
        theme = "auto",
        globalstatus = true,
    },
})

-- Fuzzy finder
require("fzf-lua").setup({})
vim.keymap.set("n", "<leader>ff", function() require("fzf-lua").files() end, { desc = "Find files" })
vim.keymap.set("n", "<leader>fg", function() require("fzf-lua").live_grep() end, { desc = "Live grep" })
vim.keymap.set("n", "<leader>fb", function() require("fzf-lua").buffers() end, { desc = "Buffers" })
vim.keymap.set("n", "<leader>fh", function() require("fzf-lua").helptags() end, { desc = "Help tags" })

-- File explorer (oil)
require("oil").setup({
    default_file_explorer = true,
    view_options = { show_hidden = true },
})
vim.keymap.set("n", "-", "<CMD>Oil<CR>", { desc = "Open parent directory" })
vim.keymap.set("n", "<leader>y", function() require("oil").toggle_float() end, { desc = "File explorer (float)" })

local alpha = require("alpha")
local dashboard = require("alpha.themes.dashboard")

dashboard.section.header.val = {
    [[ â–ˆâ–ˆâ–ˆâ•—   â–ˆâ–ˆâ•—â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ•—   â–ˆâ–ˆâ•—â–ˆâ–ˆâ•—â–ˆâ–ˆâ–ˆâ•—   â–ˆâ–ˆâ–ˆâ•— ]],
    [[ â–ˆâ–ˆâ–ˆâ–ˆâ•—  â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â•â•â•â–ˆâ–ˆâ•”â•â•â•â–ˆâ–ˆâ•—â–ˆâ–ˆâ•‘   â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ–ˆâ–ˆâ•‘ ]],
    [[ â–ˆâ–ˆâ•”â–ˆâ–ˆâ•— â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•—  â–ˆâ–ˆâ•‘   â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•‘   â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â–ˆâ–ˆâ–ˆâ–ˆâ•”â–ˆâ–ˆâ•‘ ]],
    [[ â–ˆâ–ˆâ•‘â•šâ–ˆâ–ˆâ•—â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â•  â–ˆâ–ˆâ•‘   â–ˆâ–ˆâ•‘â•šâ–ˆâ–ˆâ•— â–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•‘â•šâ–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•‘ ]],
    [[ â–ˆâ–ˆâ•‘ â•šâ–ˆâ–ˆâ–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•—â•šâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•”â• â•šâ–ˆâ–ˆâ–ˆâ–ˆâ•”â• â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•‘ â•šâ•â• â–ˆâ–ˆâ•‘ ]],
    [[ â•šâ•â•  â•šâ•â•â•â•â•šâ•â•â•â•â•â•â• â•šâ•â•â•â•â•â•   â•šâ•â•â•â•  â•šâ•â•â•šâ•â•     â•šâ•â• ]],
}

dashboard.section.buttons.val = {
    dashboard.button("f", "  Find file",     "<cmd>lua require('fzf-lua').files()<cr>"),
    dashboard.button("r", "  Recent files",  "<cmd>lua require('fzf-lua').oldfiles()<cr>"),
    dashboard.button("g", "  Find text",     "<cmd>lua require('fzf-lua').live_grep()<cr>"),
    dashboard.button("e", "  File explorer", "<cmd>Oil<cr>"),
    dashboard.button("n", "  New file",      "<cmd>ene | startinsert<cr>"),
    dashboard.button("c", "  Config",        "<cmd>edit $MYVIMRC<cr>"),
    dashboard.button("q", "  Quit",          "<cmd>qa<cr>"),
}

alpha.setup(dashboard.config)

-- LSP
vim.lsp.config("pyright", {
    settings = {
        python = {
            analysis = {
                typeCheckingMode = "basic",   -- "off" | "basic" | "strict"
                autoSearchPaths = true,
                useLibraryCodeForTypes = true,
            },
        },
    },
})


vim.lsp.enable({ "pyright", "ruff" })

-- Inline diagnostics
vim.diagnostic.config({
    virtual_text = true,
    severity_sort = true,
})

-- Buffer-local LSP keymaps + completion
vim.api.nvim_create_autocmd("LspAttach", {
    desc = "LSP keymaps & completion",
    callback = function(args)
        local buf = args.buf
        local client = vim.lsp.get_client_by_id(args.data.client_id)

        local map = function(keys, fn, desc)
            vim.keymap.set("n", keys, fn, { buffer = buf, desc = desc })
        end
        map("gd", vim.lsp.buf.definition, "Go to definition")
        map("gD", vim.lsp.buf.declaration, "Go to declaration")
        map("<leader>rn", vim.lsp.buf.rename, "Rename")
        map("<leader>ca", vim.lsp.buf.code_action, "Code action")

        if client and client.name == "ruff" then
            client.server_capabilities.hoverProvider = false
        end

        -- Autocompletion
        if client and client:supports_method("textDocument/completion") then
            vim.lsp.completion.enable(true, client.id, buf, { autotrigger = true })
        end
    end,
})

-- Autocommands

-- Briefly highlight text on yank
vim.api.nvim_create_autocmd("TextYankPost", {
    desc = "Highlight on yank",
    callback = function()
        vim.highlight.on_yank()
    end,
})

-- Restore last cursor position when reopening a file
vim.api.nvim_create_autocmd("BufReadPost", {
    desc = "Restore cursor position",
    callback = function()
        local mark = vim.api.nvim_buf_get_mark(0, '"')
        local lcount = vim.api.nvim_buf_line_count(0)
        if mark[1] > 0 and mark[1] <= lcount then
            pcall(vim.api.nvim_win_set_cursor, 0, mark)
        end
    end,
})

-- Strip trailing whitespace on save
vim.api.nvim_create_autocmd("BufWritePre", {
    desc = "Trim trailing whitespace",
    callback = function()
        local save = vim.fn.winsaveview()
        vim.cmd([[%s/\s\+$//e]])
        vim.fn.winrestview(save)
    end,
})

-- Format on save via ruff
vim.api.nvim_create_autocmd("BufWritePre", {
    desc = "Format on save (ruff)",
    callback = function(args)
        vim.lsp.buf.format({
            bufnr = args.buf,
            async = false,
            filter = function(client)
                return client.name == "ruff"
            end,
        })
    end,
})

-- Windows / PowerShell shell integration
if vim.fn.has("win32") == 1 then
    local powershell_opts = {
        shell = vim.fn.executable("pwsh") == 1 and "pwsh" or "powershell",
        shellcmdflag = "-NoLogo -NoProfile -ExecutionPolicy RemoteSigned -Command [Console]::InputEncoding=[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;",
        shellredir = "2>&1 | %%{ \"$_\" } | Out-File %s; exit $LastExitCode",
        shellpipe = "2>&1 | %%{ \"$_\" } | Tee-Object %s; exit $LastExitCode",
        shellquote = "",
        shellxquote = "",
    }
    for option, value in pairs(powershell_opts) do
        vim.opt[option] = value
    end
end
