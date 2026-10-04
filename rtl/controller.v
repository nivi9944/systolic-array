// -----------------------------------------------------------------------------
// controller.v : job sequencer for the systolic array
//
//   IDLE   --start-->  STREAM : accept K beats (one column of A + one row of B
//                               per beat). The accumulators are already zero:
//                               reset clears them and every drain shifts zeros in.
//   STREAM --K beats-> FLUSH  : 2N-1+PIPE+ISO cycles so the last beat can travel
//                               through the input register, the skew, the grid,
//                               the PE operand copy and the PE product register.
//   FLUSH  ----------> DRAIN  : present C one row per beat (row 0 first).
//   DRAIN  --N rows--> DONE   : one-cycle done pulse, then back to IDLE.
//
// Bubbles (s_valid low during STREAM) are harmless: the datapath injects zeros
// into every lane in the same cycle, so the A/B alignment is preserved.
//
// Timing-driven choices (from the physical design runs). shift drives every
// accumulator, about two thousand flip-flops through a buffer tree, so it must
// come straight from a flip-flop, never from an input pin or decode logic:
//   * The output stream uses a ready latency of 1 (as in Avalon-ST
//     readyLatency = 1): a row transfers in every cycle where m_valid is high,
//     and m_valid is only raised when m_ready was high in the previous cycle.
//     This keeps m_ready off the shift tree while keeping full throughput.
//   * shift_q feeds only the array and valid_q feeds only the m_valid pin, so
//     the output port is not a leaf of the big buffer tree. They differ in
//     IDLE, where shift_q is also high: the array is all zeros then, so
//     shifting is harmless (it only moves zeros), and the difference stops
//     synthesis from merging the two flip-flops back into one.
//   * s_ready, m_valid, m_last, busy and done are all flip-flop outputs, so no
//     decode logic sits between a register and an output pin.
// -----------------------------------------------------------------------------
module controller #(
    parameter N     = 8,
    parameter K_MAX = 64,        // longest job; larger k_len values are clamped
    parameter KW    = 7,         // width of k_len, must hold K_MAX
    parameter PIPE  = 1,         // PE product register stages (adds to flush time)
    parameter ISO   = 1          // PE operand isolation register (adds to flush time)
) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          start,
    input  wire [KW-1:0] k_len,
    input  wire          s_valid,
    input  wire          m_ready,
    output wire          s_ready,
    output wire          accept,     // a beat is taken this cycle
    output wire          shift,      // move results up one row
    output wire          m_valid,
    output wire          m_last,
    output wire          busy,
    output wire          done
);

    localparam FLUSH_CYC = 2 * N - 1 + PIPE + ISO;

    function integer clog2;
        input integer value;
        integer v;
        begin
            v = value - 1;
            clog2 = 0;
            while (v > 0) begin
                clog2 = clog2 + 1;
                v = v >> 1;
            end
        end
    endfunction

    // Counter wide enough for K beats, the flush time and N drain rows.
    localparam CW_K = (KW > clog2(FLUSH_CYC + 1)) ? KW : clog2(FLUSH_CYC + 1);
    localparam CW   = (CW_K > clog2(N + 1)) ? CW_K : clog2(N + 1);

    // Sized compare constants (keeps lint quiet about 32-bit integer math).
    localparam integer  FLUSH_LAST_I = FLUSH_CYC - 1;
    localparam integer  ROW_LAST_I   = N - 1;
    localparam [CW-1:0] FLUSH_LAST   = FLUSH_LAST_I[CW-1:0];
    localparam [CW-1:0] ROW_LAST     = ROW_LAST_I[CW-1:0];

    localparam [2:0] S_IDLE   = 3'd0,
                     S_STREAM = 3'd1,
                     S_FLUSH  = 3'd2,
                     S_DRAIN  = 3'd3,
                     S_DONE   = 3'd4;

    reg [2:0]    state, state_nx;
    reg [CW-1:0] cnt,   cnt_nx;
    reg [KW-1:0] k_reg, k_nx;
    reg          s_ready_q;   // s_ready
    reg          valid_q;     // m_valid pin
    reg          shift_q;     // array shift (same value as valid_q)
    reg          last_q;      // m_last
    reg          busy_q;      // busy pin
    reg          done_q;      // done pin

    wire [CW-1:0] k_last = {{(CW-KW){1'b0}}, k_reg} - {{(CW-1){1'b0}}, 1'b1};

    assign s_ready = s_ready_q;
    assign accept  = s_ready_q & s_valid;
    assign m_valid = valid_q;
    assign shift   = shift_q;       // a transferred row leaves the array
    assign m_last  = last_q;
    assign busy    = busy_q;        // registered: equals (state != IDLE)
    assign done    = done_q;        // registered: equals (state == DONE)

    // Next-state logic.
    always @(*) begin
        state_nx = state;
        cnt_nx   = cnt;
        k_nx     = k_reg;
        case (state)
            S_IDLE: begin
                cnt_nx = {CW{1'b0}};
                if (start) begin
                    // K is clamped to K_MAX: the accumulator width is sized
                    // for at most K_MAX products, so longer jobs are refused.
                    k_nx = (k_len > K_MAX[KW-1:0]) ? K_MAX[KW-1:0] : k_len;
                    // K = 0 is a legal (empty) job: results are all zero.
                    state_nx = (k_len == {KW{1'b0}}) ? S_FLUSH : S_STREAM;
                end
            end
            S_STREAM: begin
                if (accept) begin
                    if (cnt == k_last) begin
                        cnt_nx   = {CW{1'b0}};
                        state_nx = S_FLUSH;
                    end else begin
                        cnt_nx = cnt + 1'b1;
                    end
                end
            end
            S_FLUSH: begin
                if (cnt == FLUSH_LAST) begin
                    cnt_nx   = {CW{1'b0}};
                    state_nx = S_DRAIN;
                end else begin
                    cnt_nx = cnt + 1'b1;
                end
            end
            S_DRAIN: begin
                if (valid_q) begin
                    if (cnt == ROW_LAST) begin
                        cnt_nx   = {CW{1'b0}};
                        state_nx = S_DONE;
                    end else begin
                        cnt_nx = cnt + 1'b1;
                    end
                end
            end
            S_DONE:  state_nx = S_IDLE;
            default: state_nx = S_IDLE;
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            cnt       <= {CW{1'b0}};
            k_reg     <= {KW{1'b0}};
            s_ready_q <= 1'b0;
            valid_q   <= 1'b0;
            shift_q   <= 1'b0;
            last_q    <= 1'b0;
            busy_q    <= 1'b0;
            done_q    <= 1'b0;
        end else begin
            state     <= state_nx;
            cnt       <= cnt_nx;
            k_reg     <= k_nx;
            s_ready_q <= (state_nx == S_STREAM);
            // Row cnt_nx is offered next cycle if the consumer is ready now.
            valid_q   <= (state_nx == S_DRAIN) & m_ready;
            shift_q   <= ((state_nx == S_DRAIN) & m_ready) | (state_nx == S_IDLE);
            last_q    <= (state_nx == S_DRAIN) & m_ready & (cnt_nx == ROW_LAST);
            busy_q    <= (state_nx != S_IDLE);
            done_q    <= (state_nx == S_DONE);
        end
    end

endmodule
