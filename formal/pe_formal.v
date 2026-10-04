// -----------------------------------------------------------------------------
// pe_formal.v : formal property wrapper for rtl/pe.v
//
// Proves, for every possible input sequence (not just random samples):
//   P1 pass-through : a_out and b_out equal a_in and b_in of the previous cycle
//   P2 shift        : a shift loads acc_in of the previous cycle
//   P3 MAC          : otherwise acc = previous acc + signed(a_in) * signed(b_in)
//                     (modulo 2^ACC_W, which is how the hardware wraps); with
//                     PIPE = 1 the product used is the one registered a cycle
//                     earlier, and with ISO = 1 the operands are the copies
//                     taken one cycle before that
//
// Run with SymbiYosys (formal/pe.sby) or plain Yosys:
//   yosys -p "read_verilog -formal rtl/pe.v formal/pe_formal.v; prep -top pe_formal; flatten; \
//             async2sync; sat -tempinduct -prove-asserts -set-init-zero -seq 1 -verify"
// -----------------------------------------------------------------------------
module pe_formal #(
    parameter DATA_W = 8,
    parameter ACC_W  = 32,
    parameter PIPE   = 1,
    parameter ISO    = 1
) (
    input wire              clk,
    input wire              rst_n,
    input wire              shift,
    input wire [DATA_W-1:0] a_in,
    input wire [DATA_W-1:0] b_in,
    input wire [ACC_W-1:0]  acc_in
);

    wire [DATA_W-1:0] a_out, b_out;
    wire [ACC_W-1:0]  acc;

    pe #(.DATA_W(DATA_W), .ACC_W(ACC_W), .PIPE(PIPE), .ISO(ISO)) dut (
        .clk(clk), .rst_n(rst_n), .shift(shift),
        .a_in(a_in), .b_in(b_in), .acc_in(acc_in),
        .a_out(a_out), .b_out(b_out), .acc(acc)
    );

    // Reference model of the optional operand copy (no reset, like the RTL).
    reg  [DATA_W-1:0] ra = {DATA_W{1'b0}}, rb = {DATA_W{1'b0}};
    always @(posedge clk) begin
        ra <= a_in;
        rb <= b_in;
    end
    wire [DATA_W-1:0] ma = (ISO != 0) ? ra : a_in;
    wire [DATA_W-1:0] mb = (ISO != 0) ? rb : b_in;

    // Independent reference: sign-extend both operands to ACC_W and multiply.
    wire signed [ACC_W-1:0] a_ext = {{(ACC_W-DATA_W){ma[DATA_W-1]}}, ma};
    wire signed [ACC_W-1:0] b_ext = {{(ACC_W-DATA_W){mb[DATA_W-1]}}, mb};
    wire        [ACC_W-1:0] ref_prod = a_ext * b_ext;

    // Reference model of the optional product register.
    reg  [ACC_W-1:0] ref_q = {ACC_W{1'b0}};
    always @(posedge clk) begin
        if (!rst_n) ref_q <= {ACC_W{1'b0}};
        else                 ref_q <= ref_prod;
    end
    wire [ACC_W-1:0] ref_addend = (PIPE != 0) ? ref_q : ref_prod;

    // Remember last cycle's inputs and state.
    reg              past_valid = 1'b0;
    reg              p_rst_n, p_shift;
    reg [DATA_W-1:0] p_a, p_b;
    reg [ACC_W-1:0]  p_acc_in, p_acc, p_prod;

    always @(posedge clk) begin
        past_valid <= 1'b1;
        p_rst_n    <= rst_n;
        p_shift    <= shift;
        p_a        <= a_in;
        p_b        <= b_in;
        p_acc_in   <= acc_in;
        p_acc      <= acc;
        p_prod     <= ref_addend;
    end

    always @(*) begin
        if (past_valid && p_rst_n && rst_n) begin
            assert (a_out == p_a);                                   // P1
            assert (b_out == p_b);                                   // P1
            if (p_shift) assert (acc == p_acc_in);                   // P2
            else         assert (acc == p_acc + p_prod);             // P3
        end
    end

endmodule
