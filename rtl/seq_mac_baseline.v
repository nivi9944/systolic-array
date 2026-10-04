// -----------------------------------------------------------------------------
// seq_mac_baseline.v : single multiply-accumulate baseline, C = A x B
//
// Same ports and stream format as sa_top, but only ONE MAC unit:
//   LOAD    : store the K input beats in local buffers (K cycles)
//   COMPUTE : for i, for j, for k: acc += A[i][k] * B[k][j] (N*N*K cycles)
//   DRAIN   : output C one row per handshake (N cycles)
//
// It exists only to measure the speedup of the systolic array in simulation,
// so it is written for clarity, not for area.
// -----------------------------------------------------------------------------
module seq_mac_baseline #(
    parameter N      = 8,
    parameter DATA_W = 8,
    parameter ACC_W  = 32,
    parameter K_MAX  = 64,
    parameter KW     = 7
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 start,
    input  wire [KW-1:0]        k_len,
    output wire                 busy,
    output wire                 done,
    input  wire                 s_valid,
    output wire                 s_ready,
    input  wire [N*DATA_W-1:0]  s_a,
    input  wire [N*DATA_W-1:0]  s_b,
    output wire                 m_valid,
    input  wire                 m_ready,
    output wire [N*ACC_W-1:0]   m_data,
    output wire                 m_last
);

    localparam PROD_W = 2 * DATA_W;

    localparam [2:0] S_IDLE    = 3'd0,
                     S_LOAD    = 3'd1,
                     S_COMPUTE = 3'd2,
                     S_DRAIN   = 3'd3,
                     S_DONE    = 3'd4;

    reg [2:0]            state;
    reg                  m_ready_q;         // same ready-latency-1 output as sa_top
    reg [KW-1:0]         k_reg;
    reg [KW-1:0]         k_idx;
    reg [7:0]            i_idx, j_idx;      // up to N = 256
    reg [ACC_W-1:0]      acc;
    // Buffers are addressed by the full KW-bit index (depth 2^KW >= K_MAX).
    reg [N*DATA_W-1:0]   a_mem [0:(1<<KW)-1]; // a_mem[k] = column k of A
    reg [N*DATA_W-1:0]   b_mem [0:(1<<KW)-1]; // b_mem[k] = row k of B
    reg [N*N*ACC_W-1:0]  c_flat;            // C[i][j] at (i*N+j)*ACC_W

    // The single MAC datapath.
    wire [N*DATA_W-1:0]      a_word = a_mem[k_idx];
    wire [N*DATA_W-1:0]      b_word = b_mem[k_idx];
    wire signed [DATA_W-1:0] a_s    = a_word[i_idx*DATA_W +: DATA_W];
    wire signed [DATA_W-1:0] b_s    = b_word[j_idx*DATA_W +: DATA_W];
    wire signed [PROD_W-1:0] prod   = a_s * b_s;
    wire [ACC_W-1:0]         acc_nx = ((k_idx == 0) ? {ACC_W{1'b0}} : acc)
                                      + {{(ACC_W-PROD_W){prod[PROD_W-1]}}, prod};

    wire k_end = (k_idx == k_reg - 1'b1);
    wire j_end = (j_idx == N - 1);
    wire i_end = (i_idx == N - 1);

    assign s_ready = (state == S_LOAD);
    assign m_valid = (state == S_DRAIN) & m_ready_q;
    assign m_last  = m_valid & i_end;
    assign m_data  = c_flat[i_idx*N*ACC_W +: N*ACC_W];
    assign busy    = (state != S_IDLE);
    assign done    = (state == S_DONE);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state  <= S_IDLE;
            m_ready_q <= 1'b0;
            k_reg  <= 0;
            k_idx  <= 0;
            i_idx  <= 0;
            j_idx  <= 0;
            acc    <= 0;
            c_flat <= 0;
        end else begin
            m_ready_q <= m_ready;
            case (state)
                S_IDLE: begin
                    k_idx <= 0;
                    i_idx <= 0;
                    j_idx <= 0;
                    if (start) begin
                        k_reg  <= (k_len > K_MAX) ? K_MAX : k_len;
                        c_flat <= 0;
                        state  <= (k_len == 0) ? S_DRAIN : S_LOAD;
                    end
                end
                S_LOAD: begin
                    if (s_valid) begin
                        a_mem[k_idx] <= s_a;
                        b_mem[k_idx] <= s_b;
                        if (k_end) begin
                            k_idx <= 0;
                            state <= S_COMPUTE;
                        end else begin
                            k_idx <= k_idx + 1'b1;
                        end
                    end
                end
                S_COMPUTE: begin
                    acc <= acc_nx;
                    if (k_end) begin
                        c_flat[(i_idx*N + j_idx)*ACC_W +: ACC_W] <= acc_nx;
                        k_idx <= 0;
                        if (j_end) begin
                            j_idx <= 0;
                            if (i_end) begin
                                i_idx <= 0;
                                state <= S_DRAIN;
                            end else begin
                                i_idx <= i_idx + 1'b1;
                            end
                        end else begin
                            j_idx <= j_idx + 1'b1;
                        end
                    end else begin
                        k_idx <= k_idx + 1'b1;
                    end
                end
                S_DRAIN: begin
                    if (m_valid) begin
                        if (i_end) begin
                            i_idx <= 0;
                            state <= S_DONE;
                        end else begin
                            i_idx <= i_idx + 1'b1;
                        end
                    end
                end
                S_DONE: state <= S_IDLE;
                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
