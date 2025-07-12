import discord
from discord import app_commands
from discord.ext import commands
import os
import json
import time
import asyncio

# --- Config ---
from keep_alive import keep_alive

TOKEN = os.getenv("DISCORD_TOKEN")
AUTHORIZED_LAUNCH_ROLE = 1390820873086435460  # Role that can launch the embed
TRADER_ROLE = 1390820117352550504  # Trader role that can use the menu

# Create data directory if it doesn't exist
if not os.path.exists("data"):
    os.makedirs("data")

TRADE_OFFERS_FILE = "trade_offers.json"
NOTIFICATIONS_FILE = "data/notifications.json"
PENDING_REQUESTS_FILE = "data/pending_requests.json" # New file to store pending trade requests

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# --- Data stores ---
trade_offers = {}
notify_subscriptions = {}
pending_trade_requests = {} # Dict to store pending trade requests

# --- Utility Functions ---

async def check_auto_matches(new_user, new_offer, new_wants, guild):
    """Check for auto-matches when a new offer is posted"""
    matches = []

    for msg_id, existing_offer in trade_offers.items():
        # Skip if it's the same user
        if existing_offer['user_id'] == new_user.id:
            continue

        existing_user_id = existing_offer['user_id']
        existing_offer_item = existing_offer['offer']
        existing_wants_item = existing_offer['wants']

        # Calculate match scores
        perfect_match = False
        interest_match = False
        keyword_match = False
        match_score = 0

        # Perfect match: User A offers what User B wants AND User B offers what User A wants
        if (new_wants.lower() in existing_offer_item.lower() and 
            existing_wants_item.lower() in new_offer.lower()):
            perfect_match = True
            match_score = 100

        # Interest match: One person wants what the other offers
        elif new_wants.lower() in existing_offer_item.lower():
            interest_match = True
            match_score = 75
        elif existing_wants_item.lower() in new_offer.lower():
            interest_match = True
            match_score = 75

        # Keyword match: Similar items based on common keywords
        else:
            keywords = ['sword', 'shield', 'armor', 'weapon', 'rare', 'epic', 'legendary', 'pet', 'mount', 'accessory']
            new_keywords = [kw for kw in keywords if kw in new_offer.lower() or kw in new_wants.lower()];
            existing_keywords = [kw for kw in keywords if kw in existing_offer_item.lower() or kw in existing_wants_item.lower()]

            if new_keywords and existing_keywords and any(kw in existing_keywords for kw in new_keywords):
                keyword_match = True
                match_score = 50

        # If we found a match, add it to the list
        if perfect_match or interest_match or keyword_match:
            try:
                existing_user = await bot.fetch_user(existing_user_id)
                matches.append({
                    'user': existing_user,
                    'offer_data': existing_offer,
                    'match_type': 'Perfect' if perfect_match else 'Interest' if interest_match else 'Keyword',
                    'score': match_score
                })
            except:
                continue

    # Send auto-match notifications if matches found
    if matches:
        await send_auto_match_notifications(new_user, new_offer, new_wants, matches, guild)

async def send_auto_match_notifications(new_user, new_offer, new_wants, matches, guild):
    """Send auto-match notifications to matched users"""

    for match in matches:
        existing_user = match['user']
        existing_offer_data = match['offer_data']
        match_type = match['match_type']
        match_score = match['score']

        # Create auto-match embed for the existing user
        embed = discord.Embed(
            title="🎯 Auto-Match Found!",
            description=f"The trading system found a **{match_type} Match** ({match_score}% compatibility) with a new offer!",
            color=0x27ae60 if match_score == 100 else 0xf39c12 if match_score >= 75 else 0x3498db
        )

        embed.add_field(
            name="🆕 New Trader",
            value=f"👤 **{new_user.display_name}**",
            inline=True
        )

        embed.add_field(
            name="📊 Match Quality",
            value=f"```{match_type} Match\n{match_score}% Compatible```",
            inline=True
        )

        embed.add_field(
            name="🔄 Trade Comparison",
            value=f"**Their Offer:** {new_offer}\n**They Want:** {new_wants}\n\n**Your Offer:** {existing_offer_data['offer']}\n**You Want:** {existing_offer_data['wants']}",
            inline=False
        )

        embed.set_author(name="Auto-Match System", icon_url=new_user.display_avatar.url)
        embed.set_footer(text="💼 Baddies Trading Plaza • Auto-Match System", icon_url=guild.icon.url if guild.icon else None)
        embed.timestamp = discord.utils.utcnow()

        # Create auto-match view with accept/decline buttons
        class AutoMatchView(discord.ui.View):
            def __init__(self, new_user_obj, new_offer_text, new_wants_text, existing_user_obj, existing_offer_data, guild_obj):
                super().__init__(timeout=3600)  # 1 hour timeout
                self.new_user = new_user_obj
                self.new_offer = new_offer_text
                self.new_wants = new_wants_text
                self.existing_user = existing_user_obj
                self.existing_offer_data = existing_offer_data
                self.guild = guild_obj

            @discord.ui.button(label="✅ Accept Match", style=discord.ButtonStyle.success)
            async def accept_match(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.existing_user.id:
                    await interaction.response.send_message("❌ Only the matched trader can accept this.", ephemeral=True)
                    return

                # Send notification to the new user about the accepted match
                try:
                    new_user_embed = discord.Embed(
                        title="🎉 Auto-Match Accepted!",
                        description=f"Great news! **{self.existing_user.display_name}** accepted your auto-match!",
                        color=0x27ae60
                    )
                    new_user_embed.add_field(
                        name="📋 Trade Details",
                        value=f"**Your Offer:** {self.new_offer}\n**You Want:** {self.new_wants}\n\n**Their Offer:** {self.existing_offer_data['offer']}\n**They Want:** {self.existing_offer_data['wants']}",
                        inline=False
                    )
                    new_user_embed.add_field(
                        name="🎯 Next Steps",
                        value="A trade ticket will be created automatically for you both to finalize the trade!",
                        inline=False
                    )
                    new_user_embed.set_footer(text="💼 Baddies Trading Plaza • Auto-Match System")

                    await self.new_user.send(embed=new_user_embed)
                except:
                    pass

                # Create trade ticket automatically
                category = self.guild.get_channel(1393216235877175447)
                overwrites = {
                    self.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    self.existing_user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    self.new_user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    self.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }

                ticket_channel = await self.guild.create_text_channel(
                    name=f"automatch-{self.new_user.name}-{self.existing_user.name}",
                    category=category,
                    overwrites=overwrites
                )

                ticket_embed = discord.Embed(
                    title="🤖 Auto-Match Trade Ticket",
                    description="This ticket was created automatically by the auto-match system!",
                    color=0x27ae60
                )
                ticket_embed.add_field(
                    name=f"👤 {self.new_user.display_name}'s Offer",
                    value=f"**Offering:** {self.new_offer}\n**Wants:** {self.new_wants}",
                    inline=True
                )
                ticket_embed.add_field(
                    name=f"👤 {self.existing_user.display_name}'s Offer", 
                    value=f"**Offering:** {self.existing_offer_data['offer']}\n**Wants:** {self.existing_offer_data['wants']}",
                    inline=True
                )
                ticket_embed.set_footer(text="💼 Discuss the trade details and finalize your exchange!")

                await ticket_channel.send(
                    f"🤖 **Auto-Match Trade Ticket**\n\n"
                    f"Hello {self.new_user.mention} and {self.existing_user.mention}!\n\n"
                    f"The auto-match system detected you both have compatible trade offers. "
                    f"Use this private channel to discuss and finalize your trade!",
                    embed=ticket_embed
                )

                await interaction.response.edit_message(
                    content="✅ **Auto-match accepted!** A trade ticket has been created automatically.",
                    embed=None,
                    view=None
                )

                # Remove the auto-match request from pending
                msg_id = str(interaction.message.id)
                if msg_id in pending_trade_requests:
                    del pending_trade_requests[msg_id]
                    await save_trade_requests()

            @discord.ui.button(label="❌ Decline Match", style=discord.ButtonStyle.danger)
            async def decline_match(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.existing_user.id:
                    await interaction.response.send_message("❌ Only the matched trader can decline this.", ephemeral=True)
                    return

                await interaction.response.edit_message(
                    content="❌ **Auto-match declined.** No worries, the system will continue looking for other matches!",
                    embed=None,
                    view=None
                )

                # Remove the auto-match request from pending
                msg_id = str(interaction.message.id)
                if msg_id in pending_trade_requests:
                    del pending_trade_requests[msg_id]
                    await save_trade_requests()

            @discord.ui.button(label="💬 Contact Trader", style=discord.ButtonStyle.secondary)
            async def contact_trader(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.existing_user.id:
                    await interaction.response.send_message("❌ Only the matched trader can use this button.", ephemeral=True)
                    return

                contact_embed = discord.Embed(
                    title="📞 Contact Information",
                    description=f"You can reach out to **{self.new_user.display_name}** to discuss this trade:",
                    color=0x3498db
                )
                contact_embed.add_field(
                    name="💬 Direct Message",
                    value=f"Send a DM to {self.new_user.mention}",
                    inline=False
                )
                contact_embed.add_field(
                    name="📋 Their Trade Details",
                    value=f"**Offering:** {self.new_offer}\n**Wants:** {self.new_wants}",
                    inline=False
                )

                await interaction.response.send_message(embed=contact_embed, ephemeral=True)

        # Send auto-match notification via DM
        try:
            view = AutoMatchView(new_user, new_offer, new_wants, existing_user, existing_offer_data, guild)
            dm_msg = await existing_user.send(embed=embed, view=view)

            # Store auto-match request with timestamp for auto-deletion
            import time
            pending_trade_requests[str(dm_msg.id)] = {
                'timestamp': time.time(),
                'requester_id': new_user.id,
                'original_offerer_id': existing_user.id,
                'requested_offer': new_offer,
                'original_offer': existing_offer_data['offer'],
                'original_wants': existing_offer_data['wants'],
                'is_auto_match': True
            }
            await save_trade_requests()
        except:
            # If DM fails, we could optionally send to a channel instead
            pass

def load_trade_offers():
    global trade_offers
    if os.path.isfile(TRADE_OFFERS_FILE) and os.path.getsize(TRADE_OFFERS_FILE) > 0:
        try:
            with open(TRADE_OFFERS_FILE, "r") as f:
                trade_offers = json.load(f)
        except json.JSONDecodeError:
            trade_offers = {}
    else:
        trade_offers = {}

async def save_trade_offers():
    """Async save to prevent blocking"""
    def _save():
        with open(TRADE_OFFERS_FILE, "w") as f:
            json.dump(trade_offers, f, indent=4)

    # Run in executor to prevent blocking
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _save)

def load_notifications():
    global notify_subscriptions
    if os.path.isfile(NOTIFICATIONS_FILE) and os.path.getsize(NOTIFICATIONS_FILE) > 0:
        try:
            with open(NOTIFICATIONS_FILE, "r") as f:
                data = json.load(f)
                notify_subscriptions = {int(user_id): set(items) for user_id, items in data.items()}
        except json.JSONDecodeError:
            notify_subscriptions = {}
    else:
        notify_subscriptions = {}

async def save_notifications():
    """Async save to prevent blocking"""
    def _save():
        data = {str(user_id): list(items) for user_id, items in notify_subscriptions.items()}
        with open(NOTIFICATIONS_FILE, "w") as f:
            json.dump(data, f, indent=4)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _save)

def load_trade_requests():
    global pending_trade_requests
    if os.path.isfile(PENDING_REQUESTS_FILE) and os.path.getsize(PENDING_REQUESTS_FILE) > 0:
        try:
            with open(PENDING_REQUESTS_FILE, "r") as f:
                pending_trade_requests = json.load(f)
        except json.JSONDecodeError:
            pending_trade_requests = {}
    else:
        pending_trade_requests = {}

async def save_trade_requests():
    """Async save to prevent blocking"""
    def _save():
        with open(PENDING_REQUESTS_FILE, "w") as f:
            json.dump(pending_trade_requests, f, indent=4)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _save)

# --- Events ---

@bot.event
async def on_ready():
    load_trade_offers()
    load_notifications()
    load_trade_requests()  # Load pending trade requests
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await tree.sync()
    print("Commands synced.")

    # Clean up old trade offers on startup
    await cleanup_old_offers()

    # Start the background task to delete old requests
    bot.loop.create_task(cleanup_old_trade_requests())

async def cleanup_old_trade_requests():
    """Remove trade requests that are older than 5 hours"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            now = time.time()
            requests_to_remove = []
            for msg_id, request_data in pending_trade_requests.items():
                if 'timestamp' in request_data and (now - request_data['timestamp']) > 5 * 3600:  # 5 hours
                    requests_to_remove.append(msg_id)

            for msg_id in requests_to_remove:
                del pending_trade_requests[msg_id]

            await save_trade_requests()

            if requests_to_remove:
                print(f"🧹 Cleaned up {len(requests_to_remove)} expired trade requests")

        except Exception as e:
            print(f"❌ Error during trade request cleanup: {e}")

        await asyncio.sleep(3600)  # Check every hour

async def cleanup_old_offers():
    """Remove trade offers that no longer have valid Discord messages"""
    global trade_offers
    try:
        guild = bot.get_guild(1390975139838881823)  # Replace with your guild ID
        if not guild:
            print("Guild not found for cleanup")
            return

        offers_channel = guild.get_channel(1391947187281330206)
        if not offers_channel:
            print("Trading offers channel not found for cleanup")
            return

        valid_offers = {}
        cleanup_count = 0

        for msg_id, offer_data in trade_offers.items():
            try:
                # Try to fetch the message to see if it still exists
                await offers_channel.fetch_message(int(msg_id))
                valid_offers[msg_id] = offer_data
            except discord.NotFound:
                # Message was deleted, remove from trade offers
                cleanup_count += 1
            except discord.HTTPException:
                # Keep the offer in case of temporary network issues
                valid_offers[msg_id] = offer_data

        # Update trade_offers with only valid entries
        trade_offers = valid_offers
        await save_trade_offers()

        if cleanup_count > 0:
            print(f"🧹 Cleaned up {cleanup_count} orphaned trade offer(s)")
        else:
            print("✅ All trade offers are valid")

    except Exception as e:
        print(f"❌ Error during cleanup: {e}")

# --- Commands ---

@bot.command(name="launchembed")
async def launchembed(ctx):
    # Check if user has the authorized launch role
    user_role_ids = [role.id for role in ctx.author.roles]
    if AUTHORIZED_LAUNCH_ROLE not in user_role_ids:
        await ctx.send("❌ You are not authorized to use this command.", delete_after=5)
        return

    embed = discord.Embed(
        title="🏪 Trading Plaza Control Panel",
        description="**Welcome to the Baddies Trading Plaza management system.**\n\nSelect an action from the dropdown menu below to get started:",
        color=0x5865f2
    )
    embed.add_field(
        name="📊 Statistics",
        value=f"```📦 Active Offers: {len(trade_offers)}\n🔔 Notification Users: {len(notify_subscriptions)}```",
        inline=True
    )
    embed.add_field(
        name="⚡ Quick Info",
        value="```🛒 Create & manage offers\n🔍 Search & notifications\n📋 View your activity```",
        inline=True
    )
    embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.set_footer(text="💼 Authorized Access Only • Trading Plaza Management", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    embed.timestamp = discord.utils.utcnow()

    class TradingControlPanel(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=300)

        @discord.ui.select(
            placeholder="🎯 Choose a trading action...",
            options=[
                discord.SelectOption(label="📖 Help Guide", value="help_guide", description="Learn how to use the trading system"),
                discord.SelectOption(label="🛒 Offer", value="create_offer", description="Post a new trade offer"),
                discord.SelectOption(label="🔍 What Are You Looking For", value="search_has", description="Find who's offering a specific item"),
                discord.SelectOption(label="🔍 Is Someone Looking For", value="search_wants", description="Find who's looking for a specific item"),
                discord.SelectOption(label="🔔 Notify", value="add_notify", description="Get notified when someone offers an item"),
                discord.SelectOption(label="🔕 Remove Notify", value="remove_notify", description="Stop notifications for an item"),
                discord.SelectOption(label="📋 View My Offers", value="view_offers", description="See all your current offers"),
                discord.SelectOption(label="🗑️ Remove Offer", value="remove_offer", description="Delete one of your offers"),
                discord.SelectOption(label="📜 View Notifications", value="view_notifications", description="See your current notification subscriptions")
            ]
        )
        async def trading_select(self, select_interaction: discord.Interaction, select: discord.ui.Select):
            # Check if user has the trader role
            user_role_ids = [role.id for role in select_interaction.user.roles]
            if TRADER_ROLE not in user_role_ids:
                await select_interaction.response.send_message("❌ You need the Trader role to use this menu.", ephemeral=True)
                return

            if select.values[0] == "create_offer":
                class CreateOfferModal(discord.ui.Modal, title="🛒 Create Trade Offer"):
                    weapons_trade = discord.ui.TextInput(
                        label="What weapons do you want to trade?",
                        placeholder="e.g Loverboard, Kitty Purse, Spiked Purse",
                        required=False,
                        max_length=500
                    )
                    skins_trade = discord.ui.TextInput(
                        label="What skins do you want to trade?",
                        placeholder="Enter the skins you want to trade...",
                        required=False,
                        max_length=500
                    )
                    looking_for = discord.ui.TextInput(
                        label="What are you looking for?",
                        placeholder="Enter what you're looking for in return...",
                        required=True,
                        max_length=500
                    )

                    async def on_submit(self, modal_interaction: discord.Interaction):
                        # Use the existing offer logic
                        offers_channel = modal_interaction.guild.get_channel(1391947187281330206)
                        if not offers_channel:
                            await modal_interaction.response.send_message("Trading-offers channel not found.", ephemeral=True)
                            return

                        # Combine weapons and skins into offering field
                        offering_parts = []
                        if self.weapons_trade.value.strip():
                            offering_parts.append(f"**Weapons:** {self.weapons_trade.value}")
                        if self.skins_trade.value.strip():
                            offering_parts.append(f"**Skins:** {self.skins_trade.value}")
                        
                        if not offering_parts:
                            await modal_interaction.response.send_message("❌ You must offer at least one item (weapons or skins).", ephemeral=True)
                            return

                        offering_text = "\n".join(offering_parts)
                        combined_offer = f"{self.weapons_trade.value} {self.skins_trade.value}".strip()

                        embed = discord.Embed(
                            title="🛒 New Trade Offer",
                            description="A new trading opportunity has been posted!",
                            color=0x3498db
                        )
                        embed.add_field(name="📦 Offering", value=f"```{offering_text}```", inline=True)
                        embed.add_field(name="🎯 Looking For", value=f"```{self.looking_for.value}```", inline=True)
                        embed.add_field(name="⚡ Quick Action", value="Click the button below to request this trade", inline=False)
                        embed.set_author(name=f"{modal_interaction.user.display_name}", icon_url=modal_interaction.user.display_avatar.url)
                        embed.set_footer(text="💼 Baddies Trading Plaza", icon_url=modal_interaction.guild.icon.url if modal_interaction.guild.icon else None)
                        embed.timestamp = discord.utils.utcnow()

                        class RequestTradeButton(discord.ui.Button):
                            def __init__(self):
                                super().__init__(label="Request a trade", style=discord.ButtonStyle.primary)

                            async def callback(self, button_interaction: discord.Interaction):
                                class RequestTradeModal(discord.ui.Modal, title="Trade Request"):
                                    requested_offer = discord.ui.TextInput(
                                        label="Your Offer",
                                        placeholder="What are you offering?",
                                        required=True
                                    )

                                    async def on_submit(self, inner_modal_interaction: discord.Interaction):
                                        requester = inner_modal_interaction.user
                                        offer_msg = button_interaction.message
                                        offer_data = trade_offers.get(str(offer_msg.id))
                                        if not offer_data:
                                            await inner_modal_interaction.response.send_message("❌ This trade offer is no longer available.", ephemeral=True)
                                            return

                                        requests_channel = modal_interaction.guild.get_channel(1393265373750755388)
                                        if not requests_channel:
                                            await inner_modal_interaction.response.send_message("Trading-requests channel not found.", ephemeral=True)
                                            return

                                        embed_req = discord.Embed(
                                            title="🔔 Trade Request Incoming",
                                            description="Someone is interested in your trade offer!",
                                            color=0xf39c12
                                        )
                                        embed_req.add_field(name="👤 Requester", value=f"{requester.mention}", inline=True)
                                        embed_req.add_field(name="💰 Their Offer", value=f"```{self.requested_offer.value}```", inline=True)
                                        embed_req.add_field(name="🔄 Trade Details", value=f"**Your Offer:** {offer_data['offer']}\n**You Want:** {offer_data['wants']}", inline=False)
                                        embed_req.set_author(name=f"{requester.display_name}", icon_url=requester.display_avatar.url)
                                        embed_req.set_footer(text="💼 Baddies Trading Plaza • Accept or Decline below", icon_url=modal_interaction.guild.icon.url if modal_interaction.guild.icon else None)
                                        embed_req.timestamp = discord.utils.utcnow()

                                        class AcceptDeclineView(discord.ui.View):
                                            def __init__(self, requested_offer_value):
                                                super().__init__(timeout=None)
                                                self.requester = requester
                                                self.original_offerer_id = offer_data['user_id']
                                                self.requested_offer_value = requested_offer_value

                                            @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
                                            async def accept(self, accept_interaction: discord.Interaction, button: discord.ui.Button):
                                                if accept_interaction.user.id != self.original_offerer_id:
                                                    await accept_interaction.response.send_message("Only the original offerer can accept.", ephemeral=True)
                                                    return

                                                category = accept_interaction.guild.get_channel(1393216235877175447)
                                                overwrites = {
                                                    accept_interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                                                    accept_interaction.guild.get_member(self.original_offerer_id): discord.PermissionOverwrite(read_messages=True, send_messages=True),
                                                    self.requester: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                                                    accept_interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                                                }
                                                ticket_channel = await accept_interaction.guild.create_text_channel(
                                                    name=f"trade-{self.requester.name}-{accept_interaction.user.name}",
                                                    category=category,
                                                    overwrites=overwrites
                                                )

                                                await ticket_channel.send(
                                                    f"Trade ticket created between <@{self.original_offerer_id}> and {self.requester.mention}.\n"
                                                    f"Original offer: {offer_data['offer']} - Wants: {offer_data['wants']}\n"
                                                    f"Requester offer: {self.requested_offer_value}"
                                                )
                                                await accept_interaction.response.edit_message(content="✅ Trade accepted! Ticket created.", view=None)

                                                 # Remove the standard trade request from pending
                                                msg_id = str(accept_interaction.message.id)
                                                if msg_id in pending_trade_requests:
                                                    del pending_trade_requests[msg_id]
                                                    await save_trade_requests()

                                            @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
                                            async def decline(self, decline_interaction: discord.Interaction, button: discord.ui.Button):
                                                if decline_interaction.user.id != self.original_offerer_id:
                                                    await decline_interaction.response.send_message("Only the original offerer can decline.", ephemeral=True)
                                                    return
                                                await decline_interaction.response.edit_message(content="❌ Trade request declined.", view=None)

                                                 # Remove the standard trade request from pending
                                                msg_id = str(decline_interaction.message.id)
                                                if msg_id in pending_trade_requests:
                                                    del pending_trade_requests[msg_id]
                                                    await save_trade_requests()

                                        await requests_channel.send(f"<@{offer_data['user_id']}> You have a new trade request!", embed=embed_req, view=AcceptDeclineView(self.requested_offer.value))

                                        # Store standard trade request with timestamp for auto-deletion
                                        import time
                                        pending_trade_requests[str(button_interaction.message.id)] = {
                                            'timestamp': time.time(),
                                            'requester_id': requester.id,
                                            'original_offerer_id': offer_data['user_id'],
                                            'requested_offer': self.requested_offer.value,
                                            'original_offer': offer_data['offer'],
                                            'original_wants': offer_data['wants'],
                                            'is_auto_match': False
                                        }
                                        await save_trade_requests()
                                        await inner_modal_interaction.response.send_message("Trade request sent!", ephemeral=True)

                        view = discord.ui.View()
                        view.add_item(RequestTradeButton())

                        msg = await offers_channel.send(embed=embed, view=view)
                        trade_offers[str(msg.id)] = {
                            "user_id": modal_interaction.user.id,
                            "offer": combined_offer,
                            "wants": self.looking_for.value
                        }
                        await save_trade_offers()

                        # Check for auto-matches with existing offers
                        await check_auto_matches(modal_interaction.user, combined_offer, self.looking_for.value, modal_interaction.guild)

                        # Check for notification matches
                        offer_lower = combined_offer.lower()
                        for user_id, subscribed_items in notify_subscriptions.items():
                            if user_id == modal_interaction.user.id:
                                continue

                            for subscribed_item in subscribed_items:
                                if subscribed_item.lower() in offer_lower:
                                    try:
                                        user = await bot.fetch_user(user_id)
                                        dm_embed = discord.Embed(
                                            title="🎉 Wishlist Alert!",
                                            description=f"Great news! Someone is offering an item from your wishlist!",
                                            color=0x27ae60
                                        )
                                        dm_embed.add_field(name="🛍️ Available Item", value=f"```{offering_text}```", inline=False)
                                        dm_embed.add_field(name="📝 Your Notification", value=f"```{subscribed_item}```", inline=True)
                                        dm_embed.add_field(name="👤 Offered By", value=f"{modal_interaction.user.name}", inline=True)
                                        dm_embed.add_field(name="🎯 They Want", value=f"```{self.looking_for.value}```", inline=True)
                                        dm_embed.add_field(name="🏢 Server", value=f"{modal_interaction.guild.name}", inline=True)
                                        dm_embed.set_author(name="Wishlist Notification", icon_url=modal_interaction.user.display_avatar.url)
                                        dm_embed.set_footer(text="💼 Go to the trading-offers channel to request this trade!")
                                        dm_embed.timestamp = discord.utils.utcnow()

                                        await user.send(embed=dm_embed)
                                    except:
                                        pass
                                    break

                        await modal_interaction.response.send_message(f"✅ Your trade offer was posted in {offers_channel.mention}", ephemeral=True)

                await select_interaction.response.send_modal(CreateOfferModal())

            elif select.values[0] == "remove_offer":
                class RemoveOfferModal(discord.ui.Modal, title="🗑️ Remove Trade Offer"):
                    offer_item = discord.ui.TextInput(
                        label="Item name to remove",
                        placeholder="Enter part of the item name you want to remove...",
                        required=True
                    )

                    async def on_submit(self, modal_interaction: discord.Interaction):
                        offer = self.offer_item.value.lower().strip()
                        user_id = modal_interaction.user.id
                        removed_offers = []
                        offers_channel = modal_interaction.guild.get_channel(1391947187281330206)
                        if not offers_channel:
                            await modal_interaction.response.send_message("Trading-offers channel not found.", ephemeral=True)
                            return

                        for msg_id, offer_data in list(trade_offers.items()):
                            if offer in offer_data.get("offer", "").lower() and offer_data.get('user_id') == user_id:
                                try:
                                    msg = await offers_channel.fetch_message(int(msg_id))
                                    await msg.delete()
                                    del trade_offers[msg_id]
                                    removed_offers.append(offer_data['offer'])
                                except:
                                    del trade_offers[msg_id]
                                    removed_offers.append(offer_data['offer'])

                        await save_trade_offers()

                        if removed_offers:
                            embed = discord.Embed(
                                title="✅ Trade Offers Removed",
                                description=f"Successfully removed **{len(removed_offers)}** offer(s):",
                                color=0x27ae60
                            )
                            offers_list = "\n".join([f"🗑️ {offer}" for offer in removed_offers])
                            embed.add_field(name="Removed Offers", value=f"```{offers_list}```", inline=False)
                        else:
                            embed = discord.Embed(
                                title="❌ No Offers Found",
                                description=f"Couldn't find any of your offers containing **{offer}**",
                                color=0xe74c3c
                            )

                        embed.set_footer(text="💼 Baddies Trading Plaza")
                        embed.timestamp = discord.utils.utcnow()

                        await modal_interaction.response.send_message(embed=embed, ephemeral=True)

                await select_interaction.response.send_modal(RemoveOfferModal())

            elif select.values[0] == "search_wants":
                class SearchWantsModal(discord.ui.Modal, title="🎯 Search Who Wants Item"):
                    item_name = discord.ui.TextInput(
                        label="Item to search for",
                        placeholder="Enter the item name to find who wants it...",
                        required=True
                    )

                    async def on_submit(self, modal_interaction: discord.Interaction):
                        item = self.item_name.value.lower().strip()
                        matches = []

                        for msg_id, offer_data in trade_offers.items():
                            if item.lower() in offer_data.get("wants", "").lower():
                                try:
                                    user = await bot.fetch_user(offer_data['user_id'])
                                    matches.append((user, offer_data))
                                except:
                                    continue

                        if not matches:
                            await modal_interaction.response.send_message(f"❌ No members are currently looking for **{item}**", ephemeral=True)
                            return

                        embed = discord.Embed(
                            title=f"🎯 Who Wants **{item}**?",
                            description=f"📊 Found **{len(matches)}** member(s) currently looking for this item:",
                            color=0x27ae60
                        )

                        for user, offer_data in matches:
                            embed.add_field(
                                name=f"👤 {user.name}",
                                value=f"💰 **Offering:** ```{offer_data['offer']}```\n🎯 **Wants:** ```{offer_data['wants']}```",
                                inline=False
                            )

                        embed.set_footer(text="💼 Baddies Trading Plaza • Contact these members to make a deal!")
                        embed.timestamp = discord.utils.utcnow()

                        await modal_interaction.response.send_message(embed=embed, ephemeral=True)

                await select_interaction.response.send_modal(SearchWantsModal())

            elif select.values[0] == "search_has":
                class SearchHasModal(discord.ui.Modal, title="🛍️ Search Who Has Item"):
                    item_name = discord.ui.TextInput(
                        label="Item to search for",
                        placeholder="Enter the item name to find who's offering it...",
                        required=True
                    )

                    async def on_submit(self, modal_interaction: discord.Interaction):
                        item = self.item_name.value.lower().strip()
                        matches = []

                        for msg_id, offer_data in trade_offers.items():
                            if item.lower() in offer_data.get("offer", "").lower():
                                try:
                                    user = await bot.fetch_user(offer_data['user_id'])
                                    matches.append((user, offer_data))
                                except:
                                    continue

                        if not matches:
                            await modal_interaction.response.send_message(f"❌ No members are currently offering **{item}**", ephemeral=True)
                            return

                        embed = discord.Embed(
                            title=f"🛍️ Who's Offering **{item}**?",
                            description=f"📊 Found **{len(matches)}** member(s) currently offering this item:",
                            color=0x27ae60
                        )

                        for user, offer_data in matches:
                            embed.add_field(
                                name=f"👤 {user.name}",
                                value=f"💰 **Offering:** ```{offer_data['offer']}```\n🎯 **Wants:** ```{offer_data['wants']}```",
                                inline=False
                            )

                        embed.set_footer(text="💼 Baddies Trading Plaza • Contact these members to make a deal!")
                        embed.timestamp = discord.utils.utcnow()

                        await modal_interaction.response.send_message(embed=embed, ephemeral=True)

                await select_interaction.response.send_modal(SearchHasModal())

            elif select.values[0] == "view_offers":
                user_offers = []
                for msg_id, offer_data in trade_offers.items():
                    if offer_data.get('user_id') == select_interaction.user.id:
                        user_offers.append(offer_data)

                if not user_offers:
                    await select_interaction.response.send_message("❌ You don't have any active trade offers.", ephemeral=True)
                    return

                embed = discord.Embed(
                    title="📋 Your Active Trade Offers",
                    description=f"You have **{len(user_offers)}** active offer(s):",
                    color=0x3498db
                )

                for i, offer_data in enumerate(user_offers, 1):
                    embed.add_field(
                        name=f"🛒 Offer #{i}",
                        value=f"💰 **Offering:** ```{offer_data['offer']}```\n🎯 **Wants:** ```{offer_data['wants']}```",
                        inline=False
                    )

                embed.set_footer(text="💼 Baddies Trading Plaza • Use 'Remove Trade Offer' to delete any of these")
                embed.timestamp = discord.utils.utcnow()

                await select_interaction.response.send_message(embed=embed, ephemeral=True)

            elif select.values[0] == "view_notifications":
                user_subs = notify_subscriptions.get(select_interaction.user.id, set())

                if not user_subs:
                    await select_interaction.response.send_message("❌ You don't have any notification subscriptions.", ephemeral=True)
                    return

                embed = discord.Embed(
                    title="📬 Your Notification Subscriptions",
                    description=f"You're subscribed to **{len(user_subs)}** notification(s):",
                    color=0x3498db
                )

                subs_list = "\n".join([f"🔔 {item}" for item in sorted(user_subs)])
                embed.add_field(
                    name="Active Notifications",
                    value=f"```{subs_list}```",
                    inline=False
                )

                embed.set_footer(text="💼 You'll get DM notifications when these items are offered")
                embed.timestamp = discord.utils.utcnow()

                await select_interaction.response.send_message(embed=embed, ephemeral=True)

            elif select.values[0] == "help_guide":
                help_embed = discord.Embed(
                    title="📖 Complete Trading System Guide",
                    description="**Welcome to the Baddies Trading Plaza!** Here's everything you need to know:",
                    color=0x5865f2
                )

                help_embed.add_field(
                    name="🛒 Creating Trade Offers",
                    value="```1. Select 'Offer' from the menu\n2. Enter what you're offering\n3. Enter what you want in return\n4. Your offer gets posted automatically```",
                    inline=False
                )

                help_embed.add_field(
                    name="🔍 Finding Trades",
                    value="```• 'What Are You Looking For' - Find who has an item\n• 'Is Someone Looking For' - Find who wants an item\n• Use partial names (e.g., 'sword' finds 'Golden Sword')```",
                    inline=False
                )

                help_embed.add_field(
                    name="🔔 Smart Notifications",
                    value="```• Add items to your wishlist\n• Get instant DMs when someone offers them\n• Remove notifications anytime```",
                    inline=False
                )

                help_embed.add_field(
                    name="🤖 Auto-Match System",
                    value="```• Automatically finds compatible trades\n• Sends DM notifications for matches\n• Perfect, Interest, and Keyword matching\n• Accept/decline with one click```",
                    inline=False
                )

                help_embed.add_field(
                    name="📋 Managing Your Trades",
                    value="```• 'View My Offers' - See all your active trades\n• 'Remove Offer' - Delete specific offers\n• 'View Notifications' - Check your wishlist```",
                    inline=False
                )

                help_embed.add_field(
                    name="💡 Pro Tips",
                    value="```• Be specific in your offers (e.g., 'Rare Blue Sword +5')\n• Use keywords for better auto-matching\n• Check notifications regularly\n• Use partial searches for better results```",
                    inline=False
                )

                help_embed.set_thumbnail(url=select_interaction.guild.icon.url if select_interaction.guild.icon else None)
                help_embed.set_footer(text="💼 Baddies Trading Plaza • Happy Trading!", icon_url=select_interaction.guild.icon.url if select_interaction.guild.icon else None)
                help_embed.timestamp = discord.utils.utcnow()

                await select_interaction.response.send_message(embed=help_embed, ephemeral=True)

            elif select.values[0] == "add_notify":
                class AddNotifyModal(discord.ui.Modal, title="🔔 Add Notification"):
                    item_name = discord.ui.TextInput(
                        label="Item to get notified about",
                        placeholder="Enter the item name you want to be notified about...",
                        required=True
                    )

                    async def on_submit(self, modal_interaction: discord.Interaction):
                        item = self.item_name.value.strip()
                        user_id = modal_interaction.user.id

                        if user_id not in notify_subscriptions:
                            notify_subscriptions[user_id] = set()

                        if item.lower() in [existing.lower() for existing in notify_subscriptions[user_id]]:
                            await modal_interaction.response.send_message(f"❌ You're already subscribed to notifications for **{item}**", ephemeral=True)
                            return

                        notify_subscriptions[user_id].add(item)
                        await save_notifications()

                        embed = discord.Embed(
                            title="✅ Notification Added",
                            description=f"You'll now receive DM notifications when someone offers **{item}**!",
                            color=0x27ae60
                        )
                        embed.add_field(
                            name="📬 Your Notifications",
                            value=f"You're now subscribed to **{len(notify_subscriptions[user_id])}** notification(s)",
                            inline=False
                        )
                        embed.set_footer(text="💼 You can remove this anytime using 'Remove Notify'")
                        embed.timestamp = discord.utils.utcnow()

                        await modal_interaction.response.send_message(embed=embed, ephemeral=True)

                await select_interaction.response.send_modal(AddNotifyModal())

            elif select.values[0] == "remove_notify":
                class RemoveNotifyModal(discord.ui.Modal, title="🔕 Remove Notification"):
                    item_name = discord.ui.TextInput(
                        label="Item to stop notifications for",
                        placeholder="Enter the item name to remove from notifications...",
                        required=True
                    )

                    async def on_submit(self, modal_interaction: discord.Interaction):
                        item = self.item_name.value.strip()
                        user_id = modal_interaction.user.id

                        if user_id not in notify_subscriptions or not notify_subscriptions[user_id]:
                            await modal_interaction.response.send_message("❌ You don't have any notification subscriptions.", ephemeral=True)
                            return

                        # Find and remove the item (case insensitive)
                        removed_items = []
                        for existing_item in list(notify_subscriptions[user_id]):
                            if item.lower() in existing_item.lower():
                                notify_subscriptions[user_id].remove(existing_item)
                                removed_items.append(existing_item)

                        if not removed_items:
                            await modal_interaction.response.send_message(f"❌ You're not subscribed to notifications for **{item}**", ephemeral=True)
                            return

                        await save_notifications()

                        embed = discord.Embed(
                            title="✅ Notification Removed",
                            description=f"Successfully removed **{len(removed_items)}** notification(s):",
                            color=0x27ae60
                        )

                        removed_list = "\n".join([f"🔕 {item}" for item in removed_items])
                        embed.add_field(
                            name="Removed Notifications",
                            value=f"```{removed_list}```",
                            inline=False
                        )

                        embed.set_footer(text="💼 Baddies Trading Plaza")
                        embed.timestamp = discord.utils.utcnow()

                        await modal_interaction.response.send_message(embed=embed, ephemeral=True)

                await select_interaction.response.send_modal(RemoveNotifyModal())

    embed.set_author(name="Trading Plaza", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    await ctx.send(embed=embed, view=TradingControlPanel())

# --- Run the bot ---
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Error: DISCORD_TOKEN environment variable not found!")
        print("Please set your Discord bot token in the Secrets tab.")
    else:
        print("🤖 Starting Discord Trading Bot...")
        keep_alive()  # Start the Flask server to keep the bot alive
        bot.run(TOKEN)
