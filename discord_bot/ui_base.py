from __future__ import annotations

import discord


class SecureView(discord.ui.View):
    """Base view that rejects interactions from anyone other than the invoking user."""

    def __init__(self, user_id: int, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id:
            from discord_bot.ww1_data import set_server_context
            set_server_context(str(interaction.guild_id))
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You cannot use this interaction.", ephemeral=True
            )
            return False
        return True
