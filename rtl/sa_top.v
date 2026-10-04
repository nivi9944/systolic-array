// -----------------------------------------------------------------------------
// sa_top.v : INT8 systolic-array matrix multiplier, C = A x B
//
//   A is N x K, B is K x N, C is N x N (signed INT8 in, signed ACC_W-bit out).
//
// Streaming input (valid/ready): beat k carries column k of A and row k of B
//   s_a[i*8 +: 8] = A[i][k]      s_b[j*8 +: 8] = B[k][j]
// Streaming output (valid/ready with ready latency 1): N beats, beat i carries
// row i of C. A beat transfers in each cycle where m_valid is high; m_valid is
// only raised when m_ready was high in the previous cycle.
//   m_data[j*ACC_W +: ACC_W] = C[i][j],  m_last marks row N-1
//
// Job control: pulse start with k_len = K while busy is low; done pulses for one
// cycle after the last output row is accepted.
//
// Latency with no stalls: 1 (start) + K + (2N-1+PIPE+ISO) + N + 1 (done) cycles.
// -----------------------------------------------------------------------------
module sa_top #(
    parameter N      = 8,
    parameter DATA_W = 8,
    parameter ACC_W  = 32,
    parameter K_MAX  = 64,
    parameter KW     = 7,
    parameter PIPE   = 1,    // 1: register the product inside each PE
    parameter ISO    = 1     // 1: separate operand copy for each PE multiplier
) (
    input  wire                 clk,
    input  wire                 rst_n,
    // job control
    input  wire                 start,
    input  wire [KW-1:0]        k_len,
    output wire                 busy,
    output wire                 done,
    // input stream
    input  wire                 s_valid,
    output wire                 s_ready,
    input  wire [N*DATA_W-1:0]  s_a,
    input  wire [N*DATA_W-1:0]  s_b,
    // output stream
    output wire                 m_valid,
    input  wire                 m_ready,
    output wire [N*ACC_W-1:0]   m_data,
    output wire                 m_last
);

    wire accept, shift;

    controller #(
        .N     (N),
        .K_MAX (K_MAX),
        .KW    (KW),
        .PIPE  (PIPE),
        .ISO   (ISO)
    ) u_ctrl (
        .clk     (clk),
        .rst_n   (rst_n),
        .start   (start),
        .k_len   (k_len),
        .s_valid (s_valid),
        .m_ready (m_ready),
        .s_ready (s_ready),
        .accept  (accept),
        .shift   (shift),
        .m_valid (m_valid),
        .m_last  (m_last),
        .busy    (busy),
        .done    (done)
    );

    // Input registers: capture a beat when it is accepted, otherwise load zeros
    // (a bubble). Registering here keeps input pins off the multiplier path.
    reg [N*DATA_W-1:0] a_reg, b_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_reg <= {(N*DATA_W){1'b0}};
            b_reg <= {(N*DATA_W){1'b0}};
        end else begin
            a_reg <= accept ? s_a : {(N*DATA_W){1'b0}};
            b_reg <= accept ? s_b : {(N*DATA_W){1'b0}};
        end
    end

    wire [N*DATA_W-1:0] a_skewed, b_skewed;

    skew #(.N(N), .DATA_W(DATA_W)) u_skew_a (
        .clk  (clk),
        .rst_n(rst_n),
        .din  (a_reg),
        .dout (a_skewed)
    );

    skew #(.N(N), .DATA_W(DATA_W)) u_skew_b (
        .clk  (clk),
        .rst_n(rst_n),
        .din  (b_reg),
        .dout (b_skewed)
    );

    systolic_array #(
        .N      (N),
        .DATA_W (DATA_W),
        .ACC_W  (ACC_W),
        .PIPE   (PIPE),
        .ISO    (ISO)
    ) u_array (
        .clk     (clk),
        .rst_n   (rst_n),
        .shift   (shift),
        .a_row   (a_skewed),
        .b_col   (b_skewed),
        .acc_top (m_data)
    );

endmodule
