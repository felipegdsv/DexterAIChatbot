using Dexter.Shared;
using Dexter.Web.Services;
using Microsoft.AspNetCore.Mvc;

namespace Dexter.Web.Controllers;

[ApiController]
[Route("api/chat")]
public sealed class ChatController(ChatAgentService agent) : ControllerBase
{
    [HttpPost]
    public async Task<ChatResponse> SendAsync([FromBody] ChatRequest request, CancellationToken cancellationToken)
        => await agent.SendAsync(request.Message, cancellationToken);
}
