// -----------------------------------------------------------------------------
// pe.v : one output-stationary processing element (PE)
//
// Every clock cycle the PE
//   * multiplies the signed INT8 operands that arrive from the left (a_in) and
//     from the top (b_in) and adds the 16-bit product to its accumulator,
//   * forwards a_in to the right neighbour and b_in to the neighbour below
//     through one register each (this is what makes the array "systolic").
//
// One control input is shared by every PE in the array:
//   shift : drain mode, the accumulator loads acc_in (the value of the PE below)
//           so results move up one row per cycle and leave from the top row.
//           The bottom row loads zeros, so after a drain every accumulator is
//           zero again: the array needs no separate clear between jobs.
//
// Zero operands are used as bubbles, so the PE never needs its own valid bit:
// adding 0 * 0 leaves the running total unchanged.
//
// PIPE = 1 (default) registers the product before the accumulate, so the
// multiplier and the ACC_W-bit adder sit in different clock cycles. This
// roughly halves the critical path at the cost of one cycle of latency and a
// 16-bit register per PE. PIPE = 0 does multiply and accumulate in one cycle.
//
// ISO = 1 (default) gives the multiplier its own copy of the operands (a_m, b_m),
// separate from the pass-through registers. The pass-through path from one PE to
// the next has no logic, so the layout tools insert hold-fix delay cells on it;
// with ISO those delay cells stay on the pass-through wires instead of sitting
// in front of the multiplier. a_m / b_m have no reset (they only feed the
// multiplier, which is zero during reset because its inputs are zero), and that
// difference also keeps synthesis from merging them with a_out / b_out.
// Cost: one cycle of latency and 16 flip-flops per PE.
// -----------------------------------------------------------------------------
module pe #(
    parameter DATA_W = 8,
    parameter ACC_W  = 32,
    parameter PIPE   = 1,
    parameter ISO    = 1
) (
    input  wire                     clk,
    input  wire                     rst_n,
    input  wire                     shift,
    input  wire [DATA_W-1:0]        a_in,
    input  wire [DATA_W-1:0]        b_in,
    input  wire [ACC_W-1:0]         acc_in,
    output reg  [DATA_W-1:0]        a_out,
    output reg  [DATA_W-1:0]        b_out,
    output reg  [ACC_W-1:0]         acc
);

    localparam PROD_W = 2 * DATA_W;

    // Multiplier operands: an isolated copy (ISO = 1) or the inputs directly.
    wire [DATA_W-1:0] a_mul, b_mul;

    generate
        if (ISO != 0) begin : g_iso
            reg [DATA_W-1:0] a_m, b_m;
            always @(posedge clk) begin
                a_m <= a_in;
                b_m <= b_in;
            end
            assign a_mul = a_m;
            assign b_mul = b_m;
        end else begin : g_direct
            assign a_mul = a_in;
            assign b_mul = b_in;
        end
    endgenerate

    // Signed multiply: both operands must be declared signed for $signed math.
    wire signed [DATA_W-1:0] a_s  = a_mul;
    wire signed [DATA_W-1:0] b_s  = b_mul;
    wire signed [PROD_W-1:0] prod = a_s * b_s;

    // Product that feeds the accumulator: registered (PIPE = 1) or direct.
    wire [PROD_W-1:0] prod_acc;

    generate
        if (PIPE != 0) begin : g_pipe
            reg [PROD_W-1:0] prod_q;
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) prod_q <= {PROD_W{1'b0}};
                else        prod_q <= prod;
            end
            assign prod_acc = prod_q;
        end else begin : g_comb
            assign prod_acc = prod;
        end
    endgenerate

    // Sign-extend the product to the accumulator width.
    wire [ACC_W-1:0] prod_ext = {{(ACC_W-PROD_W){prod_acc[PROD_W-1]}}, prod_acc};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_out <= {DATA_W{1'b0}};
            b_out <= {DATA_W{1'b0}};
            acc   <= {ACC_W{1'b0}};
        end else begin
            a_out <= a_in;
            b_out <= b_in;
            if (shift)
                acc <= acc_in;
            else
                acc <= acc + prod_ext;
        end
    end

endmodule
